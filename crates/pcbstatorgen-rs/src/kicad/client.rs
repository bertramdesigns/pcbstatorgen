//! KiCad IPC API client — NNG req/rep transport, protobuf envelope packing,
//! and transport abstraction for testing.
//!
//! ## Architecture
//! - [`KicadTransport`] trait abstracts the raw socket so tests can inject a
//!   [`MockTransport`].
//! - [`NngTransport`] is the production transport using the `nng` crate's
//!   `Req0` protocol over an IPC socket.
//! - [`KiCadClient`] is the high-level client that packs commands into
//!   `ApiRequest` envelopes, sends them via the transport, and unpacks
//!   `ApiResponse` replies into typed response messages.

use std::fmt;
use std::path::Path;
use std::time::Duration;

use prost::Message;
use prost_types::Any;

use crate::kicad::errors::KiCadError;
use crate::kicad::{
    ApiRequest, ApiRequestHeader, ApiResponse, ApiStatusCode,
};

// ---------------------------------------------------------------------------
// KicadTransport trait
// ---------------------------------------------------------------------------

/// Transport abstraction for the KiCad IPC socket.
///
/// Implementations:
/// - [`NngTransport`] — production, uses the `nng` crate's `Req0` protocol.
/// - [`MockTransport`] — testing, records sent bytes and returns canned
///   responses.
///
/// The default `connect` implementation is a no-op, suitable for transports
/// that don't need explicit connection management (e.g. the mock).
pub trait KicadTransport {
    /// Opens the transport connection.
    ///
    /// The default implementation is a no-op, suitable for transports that
    /// either connect lazily or don't need a connection at all (e.g.
    /// [`MockTransport`]).
    fn connect(&mut self) -> Result<(), KiCadError> {
        Ok(())
    }

    /// Sends `request_bytes` to KiCad and returns the raw reply bytes.
    fn send_and_recv(&mut self, request_bytes: &[u8]) -> Result<Vec<u8>, KiCadError>;
}

impl fmt::Debug for dyn KicadTransport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("KicadTransport").finish()
    }
}

// ---------------------------------------------------------------------------
// KiCadClient
// ---------------------------------------------------------------------------

/// High-level KiCad IPC API client.
///
/// Wraps a [`KicadTransport`] and handles protobuf envelope packing/unpacking:
///
/// 1. Encodes the command into a [`prost_types::Any`] message.
/// 2. Builds an [`ApiRequest`] envelope with `kicad_token` and `client_name`.
/// 3. Serializes the envelope, sends it via the transport, receives the reply.
/// 4. Decodes the [`ApiResponse`], checks the status code, caches the token,
///    and unpacks the `Any` payload into the expected response type.
pub struct KiCadClient {
    transport: Box<dyn KicadTransport>,
    client_name: String,
    kicad_token: String,
    #[allow(dead_code)]
    timeout_ms: u32,
    connected: bool,
}

impl KiCadClient {
    /// Creates a new client that will connect to the given socket path (or the
    /// default path resolved from `KICAD_API_SOCKET` / platform default).
    ///
    /// The `kicad_token` is read from the `KICAD_API_TOKEN` environment
    /// variable (empty string if unset). If `client_name` is `None`, a random
    /// name is generated.
    pub fn new(socket_path: Option<&str>, client_name: Option<&str>, timeout_ms: u32) -> Self {
        let socket_path = socket_path
            .map(String::from)
            .or_else(|| std::env::var("KICAD_API_SOCKET").ok())
            .unwrap_or_else(default_socket_path);

        let client_name = client_name
            .map(String::from)
            .unwrap_or_else(random_client_name);

        let kicad_token = std::env::var("KICAD_API_TOKEN").unwrap_or_default();

        let transport: Box<dyn KicadTransport> =
            Box::new(NngTransport::new(socket_path, timeout_ms));

        Self {
            transport,
            client_name,
            kicad_token,
            timeout_ms,
            connected: false,
        }
    }

    /// Creates a client with a pre-injected transport (for testing).
    ///
    /// The client starts in the "connected" state, so [`send`](Self::send) can
    /// be called immediately without calling [`connect`](Self::connect).
    pub fn with_transport(
        transport: Box<dyn KicadTransport>,
        client_name: Option<&str>,
        timeout_ms: u32,
    ) -> Self {
        let client_name = client_name
            .map(String::from)
            .unwrap_or_else(random_client_name);

        let kicad_token = std::env::var("KICAD_API_TOKEN").unwrap_or_default();

        Self {
            transport,
            client_name,
            kicad_token,
            timeout_ms,
            connected: true,
        }
    }

    /// Opens the NNG socket connection.
    ///
    /// If already connected, this is a no-op.
    pub fn connect(&mut self) -> Result<(), KiCadError> {
        if self.connected {
            return Ok(());
        }
        self.transport.connect()?;
        self.connected = true;
        Ok(())
    }

    /// Returns `true` if the client is connected.
    pub fn connected(&self) -> bool {
        self.connected
    }

    /// Returns the cached `kicad_token` (may be empty until a response is
    /// received from KiCad).
    pub fn kicad_token(&self) -> &str {
        &self.kicad_token
    }

    /// Returns the client name used in request headers.
    pub fn client_name(&self) -> &str {
        &self.client_name
    }

    /// Sends a command to KiCad and unpacks the response.
    ///
    /// ## Type parameters
    /// - `Cmd` — the command message type (must implement [`prost::Message`]).
    /// - `Resp` — the expected response message type (must implement
    ///   [`prost::Message`] + [`Default`]).
    ///
    /// ## Arguments
    /// - `type_url` — the protobuf type URL for the command, e.g.
    ///   `"type.googleapis.com/kiapi.common.commands.Ping"`.
    /// - `command` — the command message to send.
    ///
    /// ## Protocol
    /// 1. Encodes `command` to bytes and packs into [`prost_types::Any`].
    /// 2. Builds an [`ApiRequest`] envelope with the current `kicad_token` and
    ///    `client_name`.
    /// 3. Serializes the envelope, sends via [`KicadTransport::send_and_recv`].
    /// 4. Decodes the reply as [`ApiResponse`].
    /// 5. Checks `status.status == AS_OK`; returns [`KiCadError::Api`] on
    ///    non-OK status.
    /// 6. Caches `kicad_token` from the response header (if previously empty).
    /// 7. Unpacks `response.message` (Any) into `Resp` and returns it.
    pub fn send<Cmd, Resp>(
        &mut self,
        type_url: &str,
        command: &Cmd,
    ) -> Result<Resp, KiCadError>
    where
        Cmd: Message,
        Resp: Message + Default,
    {
        if !self.connected {
            self.connect()?;
        }

        // 1. Encode the command to bytes.
        let mut cmd_buf = Vec::new();
        command
            .encode(&mut cmd_buf)
            .map_err(|e| KiCadError::Protocol(format!("failed to encode command: {e}")))?;

        // 2. Pack into google.protobuf.Any.
        let any = Any {
            type_url: type_url.to_string(),
            value: cmd_buf,
        };

        // 3. Build the ApiRequest envelope.
        let request = ApiRequest {
            header: Some(ApiRequestHeader {
                kicad_token: self.kicad_token.clone(),
                client_name: self.client_name.clone(),
            }),
            message: Some(any),
        };

        // 4. Serialize the envelope.
        let mut req_bytes = Vec::new();
        request
            .encode(&mut req_bytes)
            .map_err(|e| KiCadError::Protocol(format!("failed to encode ApiRequest: {e}")))?;

        // 5. Send via transport and receive reply.
        let resp_bytes = self.transport.send_and_recv(&req_bytes)?;

        // 6. Decode the reply as ApiResponse.
        let response = ApiResponse::decode(resp_bytes.as_slice())
            .map_err(|e| KiCadError::Protocol(format!("failed to decode ApiResponse: {e}")))?;

        // 7. Check status code.
        let status = response.status.unwrap_or_default();
        if status.status != ApiStatusCode::AsOk as i32 {
            return Err(KiCadError::Api {
                code: status.status,
                message: status.error_message,
            });
        }

        // 8. Cache kicad_token from response header (if previously empty).
        if let Some(header) = &response.header {
            if self.kicad_token.is_empty() {
                self.kicad_token = header.kicad_token.clone();
            }
        }

        // 9. Unpack the Any payload into the expected Resp type.
        let any = response.message.ok_or_else(|| {
            KiCadError::Protocol("response message (Any) is None".to_string())
        })?;
        let resp = Resp::decode(any.value.as_slice())
            .map_err(|e| KiCadError::Protocol(format!("failed to decode response: {e}")))?;

        Ok(resp)
    }
}

// ---------------------------------------------------------------------------
// NngTransport (production)
// ---------------------------------------------------------------------------

/// NNG-based transport using the `Req0` (request/reply) protocol.
///
/// The socket is lazily opened: [`connect`](KicadTransport::connect) opens it,
/// but [`send_and_recv`](KicadTransport::send_and_recv) will also auto-connect
/// if needed.
struct NngTransport {
    socket_path: String,
    timeout_ms: u32,
    socket: Option<nng::Socket>,
}

impl NngTransport {
    fn new(socket_path: String, timeout_ms: u32) -> Self {
        Self {
            socket_path,
            timeout_ms,
            socket: None,
        }
    }

    fn ensure_connected(&mut self) -> Result<(), KiCadError> {
        if self.socket.is_some() {
            return Ok(());
        }
        self.connect_impl()
    }

    fn connect_impl(&mut self) -> Result<(), KiCadError> {
        use nng::options::{Options, RecvTimeout, SendTimeout};

        let socket = nng::Socket::new(nng::Protocol::Req0).map_err(|e| {
            KiCadError::Connection(format!("failed to create NNG Req0 socket: {e}"))
        })?;

        let timeout = Duration::from_millis(self.timeout_ms as u64);
        socket
            .set_opt::<SendTimeout>(Some(timeout))
            .map_err(|e| KiCadError::Connection(format!("failed to set send timeout: {e}")))?;
        socket
            .set_opt::<RecvTimeout>(Some(timeout))
            .map_err(|e| KiCadError::Connection(format!("failed to set recv timeout: {e}")))?;

        socket
            .dial(&self.socket_path)
            .map_err(|e| {
                KiCadError::Connection(format!(
                    "failed to dial {}: {e}",
                    self.socket_path
                ))
            })?;

        self.socket = Some(socket);
        Ok(())
    }
}

impl KicadTransport for NngTransport {
    fn connect(&mut self) -> Result<(), KiCadError> {
        if self.socket.is_some() {
            return Ok(());
        }
        self.connect_impl()
    }

    fn send_and_recv(&mut self, request_bytes: &[u8]) -> Result<Vec<u8>, KiCadError> {
        self.ensure_connected()?;

        let socket = self.socket.as_ref().unwrap();

        socket
            .send(request_bytes)
            .map_err(|(_, e)| KiCadError::Connection(format!("NNG send failed: {e}")))?;

        let msg = socket
            .recv()
            .map_err(|e| KiCadError::Connection(format!("NNG recv failed: {e}")))?;

        Ok(msg.to_vec())
    }
}

// ---------------------------------------------------------------------------
// MockTransport (testing)
// ---------------------------------------------------------------------------

/// Mock transport for offline testing.
///
/// Records every request sent via [`send_and_recv`](KicadTransport::send_and_recv)
/// into [`sent_requests`] and returns `response_to_return` (a clone) on each
/// call. This lets tests:
/// - Inspect the exact bytes the client packed into the `ApiRequest` envelope.
/// - Control the canned `ApiResponse` bytes the client will decode.
pub struct MockTransport {
    /// All requests sent by the client, in order.
    pub sent_requests: Vec<Vec<u8>>,
    /// The raw response bytes returned on each `send_and_recv` call.
    pub response_to_return: Vec<u8>,
}

impl MockTransport {
    /// Creates a mock transport that returns the given response bytes.
    pub fn new(response_to_return: Vec<u8>) -> Self {
        Self {
            sent_requests: Vec::new(),
            response_to_return,
        }
    }
}

impl KicadTransport for MockTransport {
    fn send_and_recv(&mut self, request_bytes: &[u8]) -> Result<Vec<u8>, KiCadError> {
        self.sent_requests.push(request_bytes.to_vec());
        Ok(self.response_to_return.clone())
    }
}

// ---------------------------------------------------------------------------
// Socket path resolution & client name generation
// ---------------------------------------------------------------------------

/// Resolves the default KiCad IPC socket path.
///
/// Priority:
/// 1. `KICAD_API_SOCKET` environment variable (handled by caller).
/// 2. Flatpak cache path (if it exists on non-Windows).
/// 3. Platform default:
///    - macOS/Linux: `ipc:///tmp/kicad/api.sock`
///    - Windows: `ipc://%TEMP%\kicad\api.sock`
fn default_socket_path() -> String {
    if cfg!(target_os = "windows") {
        let temp = std::env::var("TEMP").unwrap_or_else(|_| "C:\\temp".to_string());
        format!("ipc://{temp}\\kicad\\api.sock")
    } else {
        // Check for KiCad flatpak socket on non-Windows.
        if let Some(home) = std::env::var_os("HOME") {
            let flatpak_socket = Path::new(&home)
                .join(".var/app/org.kicad.KiCad/cache/tmp/kicad/api.sock");
            if flatpak_socket.exists() {
                return format!("ipc://{}", flatpak_socket.display());
            }
        }
        "ipc:///tmp/kicad/api.sock".to_string()
    }
}

/// Generates a random client name: `pcbstatorgen-<8 alphanumeric chars>`.
///
/// Mirrors the Python `kipy._random_client_name()` pattern.
fn random_client_name() -> String {
    use rand::Rng;
    let suffix: String = rand::thread_rng()
        .sample_iter(&rand::distributions::Alphanumeric)
        .take(8)
        .map(char::from)
        .collect();
    format!("pcbstatorgen-{suffix}")
}

// ---------------------------------------------------------------------------
// Tests (inline unit tests for helpers)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_random_client_name_format() {
        let name = random_client_name();
        assert!(name.starts_with("pcbstatorgen-"));
        assert_eq!(name.len(), "pcbstatorgen-".len() + 8);
    }

    #[test]
    fn test_default_socket_path_non_windows() {
        // On non-Windows, should be the default unless flatpak path exists.
        // We can't control the flatpak path in CI, so just check the format.
        let path = default_socket_path();
        assert!(
            path.starts_with("ipc://"),
            "socket path should start with ipc://, got: {path}"
        );
    }
}
