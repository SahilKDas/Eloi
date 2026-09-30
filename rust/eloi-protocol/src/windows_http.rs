//! Windows-native asynchronous HTTP with safe bindings and explicit cancellation.
//! No `WinHTTP` raw handles, TLS exceptions, redirects or credential diagnostics.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant};

use windows::{
    Foundation::Uri,
    Storage::Streams::{Buffer, DataReader, InputStreamOptions, UnicodeEncoding},
    Web::Http::{
        Filters::{HttpBaseProtocolFilter, HttpCookieUsageBehavior},
        HttpClient, HttpCompletionOption, HttpMethod, HttpRequestMessage, HttpStringContent,
    },
    core::{HSTRING, RuntimeType},
};
use windows_future::{AsyncStatus, IAsyncOperationWithProgress};

use crate::transport::{Reply, Transport};

/// Native HTTP adapter. Creating it is inert until a request is explicitly made.
pub struct WindowsHttp {
    client: HttpClient,
    token: String,
    generation: AtomicU64,
}

fn valid_path(path: &str) -> bool {
    path.starts_with("/api/")
        && path.len() <= 512
        && !path.contains("..")
        && !path.contains("//")
        && path.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(byte, b'/' | b'_' | b'-' | b'?' | b'=' | b'&' | b'%')
        })
}

impl WindowsHttp {
    /// Construct only for a nonempty header-safe token; no network call occurs.
    ///
    /// # Errors
    /// Rejects invalid credentials or unavailable OS HTTP services without echoing secrets.
    pub fn new(token: &str) -> Result<Self, &'static str> {
        if token.is_empty()
            || token.len() > 512
            || !token
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        {
            return Err("invalid Lichess credential syntax");
        }
        let filter =
            HttpBaseProtocolFilter::new().map_err(|_| "Windows HTTP filter unavailable")?;
        filter
            .SetAllowAutoRedirect(false)
            .map_err(|_| "could not disable redirects")?;
        filter
            .SetAllowUI(false)
            .map_err(|_| "could not disable HTTP prompts")?;
        filter
            .SetCookieUsageBehavior(HttpCookieUsageBehavior::NoCookies)
            .map_err(|_| "could not disable HTTP cookies")?;
        let client = HttpClient::Create(&filter).map_err(|_| "Windows HTTP client unavailable")?;
        Ok(Self {
            client,
            token: token.into(),
            generation: AtomicU64::new(0),
        })
    }

    fn wait<T: RuntimeType + 'static, P: RuntimeType + 'static>(
        &self,
        operation: &IAsyncOperationWithProgress<T, P>,
        cancelled: &AtomicBool,
        generation: u64,
        timeout: Duration,
    ) -> Result<T, &'static str> {
        let deadline = Instant::now() + timeout;
        loop {
            if cancelled.load(Ordering::Relaxed)
                || self.generation.load(Ordering::Relaxed) != generation
            {
                let _ = operation.Cancel();
                return Err("HTTP operation cancelled");
            }
            match operation
                .Status()
                .map_err(|_| "HTTP operation status failed")?
            {
                AsyncStatus::Completed => {
                    return operation.GetResults().map_err(|_| "HTTP operation failed");
                }
                AsyncStatus::Canceled => return Err("HTTP operation cancelled"),
                AsyncStatus::Error => return Err("HTTP operation failed"),
                _ => {}
            }
            if Instant::now() >= deadline {
                let _ = operation.Cancel();
                return Err("HTTP operation timed out");
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn build_request(
        &self,
        path: &str,
        form: Option<&str>,
    ) -> Result<HttpRequestMessage, &'static str> {
        if !valid_path(path) {
            return Err("invalid Lichess API path");
        }
        if form.is_some_and(|form| form.len() > 8192 || !form.is_ascii()) {
            return Err("invalid HTTP form");
        }
        let uri = Uri::CreateUri(&HSTRING::from(format!("https://lichess.org{path}")))
            .map_err(|_| "invalid Lichess URI")?;
        let method = if form.is_some() {
            HttpMethod::Post()
        } else {
            HttpMethod::Get()
        }
        .map_err(|_| "HTTP method unavailable")?;
        let request =
            HttpRequestMessage::Create(&method, &uri).map_err(|_| "HTTP request unavailable")?;
        let headers = request.Headers().map_err(|_| "HTTP headers unavailable")?;
        if !headers
            .TryAppendWithoutValidation(
                &HSTRING::from("Authorization"),
                &HSTRING::from(format!("Bearer {}", self.token)),
            )
            .map_err(|_| "HTTP authorization setup failed")?
        {
            return Err("HTTP authorization setup failed");
        }
        headers
            .TryAppendWithoutValidation(
                &HSTRING::from("User-Agent"),
                &HSTRING::from("Eloi-Rust-Rewrite"),
            )
            .map_err(|_| "HTTP user agent setup failed")?;
        if let Some(form) = form {
            let content = HttpStringContent::CreateFromStringWithEncodingAndMediaType(
                &HSTRING::from(form),
                UnicodeEncoding::Utf8,
                &HSTRING::from("application/x-www-form-urlencoded"),
            )
            .map_err(|_| "HTTP content setup failed")?;
            request
                .SetContent(&content)
                .map_err(|_| "HTTP content setup failed")?;
        }
        Ok(request)
    }

    fn request(
        &self,
        path: &str,
        form: Option<&str>,
        cancelled: &AtomicBool,
        consumer: &mut dyn FnMut(&[u8]) -> bool,
        streaming: bool,
    ) -> Result<Reply, &'static str> {
        if cancelled.load(Ordering::Relaxed) {
            return Err("HTTP operation cancelled");
        }
        let generation = self.generation.load(Ordering::Relaxed);
        let request = self.build_request(path, form)?;
        let send = self
            .client
            .SendRequestWithOptionAsync(&request, HttpCompletionOption::ResponseHeadersRead)
            .map_err(|_| "HTTP send failed")?;
        let response = self.wait(&send, cancelled, generation, Duration::from_secs(15))?;
        let status = u16::try_from(
            response
                .StatusCode()
                .map_err(|_| "HTTP status unavailable")?
                .0,
        )
        .map_err(|_| "invalid HTTP status")?;
        let retry_after_seconds = response
            .Headers()
            .ok()
            .and_then(|headers| headers.Lookup(&HSTRING::from("Retry-After")).ok())
            .and_then(|value| value.to_string().parse::<u32>().ok());
        let mut reply = Reply {
            status,
            retry_after_seconds,
            body: Vec::new(),
        };
        // Never follow redirects or consume unbounded error bodies.
        if !(200..=299).contains(&status) {
            return Ok(reply);
        }
        let content = response.Content().map_err(|_| "HTTP body unavailable")?;
        let open = content
            .ReadAsInputStreamAsync()
            .map_err(|_| "HTTP stream unavailable")?;
        let stream = self.wait(&open, cancelled, generation, Duration::from_secs(15))?;
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let buffer = Buffer::Create(4096).map_err(|_| "HTTP buffer unavailable")?;
            let read = stream
                .ReadAsync(&buffer, 4096, InputStreamOptions::Partial)
                .map_err(|_| "HTTP read failed")?;
            let timeout = if streaming {
                Duration::from_secs(60)
            } else {
                deadline.saturating_duration_since(Instant::now())
            };
            let buffer = self.wait(&read, cancelled, generation, timeout)?;
            let length = usize::try_from(
                buffer
                    .Length()
                    .map_err(|_| "HTTP buffer length unavailable")?,
            )
            .map_err(|_| "HTTP buffer length invalid")?;
            if length == 0 {
                break;
            }
            if length > 4096 {
                return Err("HTTP buffer exceeds limit");
            }
            let mut bytes = vec![0; length];
            DataReader::FromBuffer(&buffer)
                .and_then(|reader| reader.ReadBytes(&mut bytes))
                .map_err(|_| "HTTP buffer decode failed")?;
            if streaming {
                if !consumer(&bytes) {
                    break;
                }
            } else {
                if reply.body.len() + length > 65_536 {
                    return Err("HTTP response exceeds limit");
                }
                reply.body.extend_from_slice(&bytes);
            }
        }
        Ok(reply)
    }
}

impl Transport for WindowsHttp {
    fn account(&self, cancelled: &AtomicBool) -> Result<Reply, &'static str> {
        self.request("/api/account", None, cancelled, &mut |_| true, false)
    }
    fn post(&self, path: &str, form: &str, cancelled: &AtomicBool) -> Result<Reply, &'static str> {
        self.request(path, Some(form), cancelled, &mut |_| true, false)
    }
    fn stream(
        &self,
        path: &str,
        cancelled: &AtomicBool,
        consumer: &mut dyn FnMut(&[u8]) -> bool,
    ) -> Result<Reply, &'static str> {
        self.request(path, None, cancelled, consumer, true)
    }
    fn cancel(&self) {
        self.generation.fetch_add(1, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn origin_and_header_injection_fail_closed() {
        for path in [
            "https://evil.example/api/account",
            "//evil.example/api/account",
            "/api/../account",
            "/api/account\r\nHeader: secret",
        ] {
            assert!(!valid_path(path));
        }
        assert!(valid_path("/api/bot/game/stream/Abcd1234"));
        assert!(WindowsHttp::new("secret\r\nHeader: value").is_err());
        assert!(WindowsHttp::new("").is_err());
    }

    #[test]
    fn cancellation_before_request_never_opens_network() {
        let transport = WindowsHttp::new("lip_offline_fixture").unwrap();
        assert!(transport.account(&AtomicBool::new(true)).is_err());
    }

    #[test]
    fn pending_async_operation_cancels_without_raw_handle_races() {
        let transport = std::sync::Arc::new(WindowsHttp::new("lip_offline_fixture").unwrap());
        let operation = IAsyncOperationWithProgress::<u32, u32>::spawn(|| {
            std::thread::sleep(Duration::from_millis(250));
            Ok(7)
        });
        let generation = transport.generation.load(Ordering::Relaxed);
        let stopper = std::sync::Arc::clone(&transport);
        let handle = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(20));
            stopper.cancel();
        });
        let started = Instant::now();
        assert!(
            transport
                .wait(
                    &operation,
                    &AtomicBool::new(false),
                    generation,
                    Duration::from_secs(1)
                )
                .is_err()
        );
        assert!(started.elapsed() < Duration::from_millis(200));
        handle.join().unwrap();
        let ready = IAsyncOperationWithProgress::<u32, u32>::ready(Ok(9));
        assert_eq!(
            transport
                .wait(
                    &ready,
                    &AtomicBool::new(false),
                    transport.generation.load(Ordering::Relaxed),
                    Duration::from_secs(1)
                )
                .unwrap(),
            9
        );
    }
}
