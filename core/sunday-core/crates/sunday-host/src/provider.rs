//! Provider endpoint security.
//!
//! Three problems this closes, all of which were real before it existed:
//!
//! 1. **The key was not bound to anything.** A user configured OpenAI, and any
//!    later edit to `base_url` silently sent the same key to the new host. A
//!    tampered config file was enough to exfiltrate it.
//! 2. **Redirects were followed.** `reqwest` follows up to ten by default. An
//!    endpoint that answers `302` to an attacker's host moves the request there.
//! 3. **`http://` was accepted silently.** Plain HTTP puts the key and the whole
//!    prompt on the wire in clear text for anything on the path to read.
//!
//! The rules now:
//!
//!   * `https` is required, except for loopback and private-range hosts, which
//!     must be opted into explicitly (`allow_insecure_local`). A local model is a
//!     legitimate case; a silent downgrade is not.
//!   * the key is stored against a fingerprint of scheme+host+port. A key that
//!     does not match the current endpoint is not sent.
//!   * redirects are disabled at the client, so "follow" is not a decision this
//!     layer can get wrong.
//!   * the key is redacted from anything that could reach a log, an error string,
//!     an event payload or the UI.

use std::fmt;

/// A validated provider endpoint.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Endpoint {
    scheme: String,
    host: String,
    port: u16,
    /// Path prefix, without a trailing slash. May be empty.
    base_path: String,
    /// True when this endpoint is not TLS-protected and was explicitly allowed.
    insecure_local: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EndpointError {
    /// Not a URL at all.
    Malformed(String),
    /// A scheme other than http/https.
    UnsupportedScheme(String),
    /// `http://` to a host that is not local, and the caller did not opt in.
    PlainHttpRemote { host: String },
    /// `http://` to a local host without the explicit opt-in.
    PlainHttpNotAcknowledged { host: String },
    /// Credentials embedded in the URL. They would be logged and stored.
    EmbeddedCredentials,
    /// A fragment or query in the base URL would silently change the request.
    UnexpectedComponent(String),
    /// An empty host, or a host that cannot be a provider address.
    BadHost(String),
    /// A port that cannot be a provider port.
    BadPort,
}

impl fmt::Display for EndpointError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Malformed(reason) => write!(f, "not a valid URL: {reason}"),
            Self::UnsupportedScheme(scheme) => write!(
                f,
                "unsupported scheme {scheme:?}: only http and https are accepted"
            ),
            Self::PlainHttpRemote { host } => write!(
                f,
                "refusing plain http to {host}: the API key would travel in clear text. \
                 Use https, or allow insecure local endpoints explicitly for a local model"
            ),
            Self::PlainHttpNotAcknowledged { host } => write!(
                f,
                "refusing plain http to {host} without acknowledgement: enable \
                 allow_insecure_local if this really is a local model server"
            ),
            Self::EmbeddedCredentials => write!(
                f,
                "credentials in the URL are refused: they would be stored and logged"
            ),
            Self::UnexpectedComponent(what) => {
                write!(f, "the base URL must not contain a {what}")
            }
            Self::BadHost(reason) => write!(f, "invalid host: {reason}"),
            Self::BadPort => write!(f, "invalid port"),
        }
    }
}

impl std::error::Error for EndpointError {}

/// How strict to be about transport.
///
/// `Default` is the strict policy on purpose: `false` is not a placeholder, it is the
/// decision. A silent downgrade to plain HTTP is how a key ends up in clear text
/// without anyone deciding it should.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TransportPolicy {
    /// Allow `http://` to a loopback or private-range host.
    pub allow_insecure_local: bool,
}

impl Endpoint {
    /// Parses and validates a base URL.
    pub fn parse(raw: &str, policy: TransportPolicy) -> Result<Self, EndpointError> {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            return Err(EndpointError::Malformed("empty".into()));
        }
        let parsed =
            url::Url::parse(trimmed).map_err(|e| EndpointError::Malformed(e.to_string()))?;

        let scheme = parsed.scheme().to_ascii_lowercase();
        if scheme != "http" && scheme != "https" {
            return Err(EndpointError::UnsupportedScheme(scheme));
        }
        if !parsed.username().is_empty() || parsed.password().is_some() {
            return Err(EndpointError::EmbeddedCredentials);
        }
        if parsed.fragment().is_some() {
            return Err(EndpointError::UnexpectedComponent("fragment".into()));
        }
        if parsed.query().is_some() {
            return Err(EndpointError::UnexpectedComponent("query string".into()));
        }

        let host = parsed
            .host_str()
            .ok_or_else(|| EndpointError::BadHost("missing".into()))?
            .to_ascii_lowercase();
        if host.is_empty() {
            return Err(EndpointError::BadHost("empty".into()));
        }
        if host.contains('*') {
            return Err(EndpointError::BadHost(format!(
                "{host} contains a wildcard, which is ambiguous"
            )));
        }

        let default_port = if scheme == "https" { 443 } else { 80 };
        let port = parsed.port().unwrap_or(default_port);

        let mut insecure_local = false;
        if scheme == "http" {
            let local = is_local_host(&host);
            if !local {
                return Err(EndpointError::PlainHttpRemote { host });
            }
            if !policy.allow_insecure_local {
                return Err(EndpointError::PlainHttpNotAcknowledged { host });
            }
            insecure_local = true;
        }

        let base_path = parsed.path().trim_end_matches('/').to_owned();
        Ok(Self {
            scheme,
            host,
            port,
            base_path,
            insecure_local,
        })
    }

    pub fn scheme(&self) -> &str {
        &self.scheme
    }

    pub fn host(&self) -> &str {
        &self.host
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn is_insecure_local(&self) -> bool {
        self.insecure_local
    }

    /// The base URL to hand a client. Never contains credentials.
    pub fn base_url(&self) -> String {
        let default_port = if self.scheme == "https" { 443 } else { 80 };
        let authority = if self.port == default_port {
            self.host.clone()
        } else {
            format!("{}:{}", self.host, self.port)
        };
        format!("{}://{}{}", self.scheme, authority, self.base_path)
    }

    /// Identifies *where a key may be sent*, independent of the path.
    ///
    /// Path is excluded on purpose: moving from `/v1` to `/v2` on the same host
    /// is the same trust decision, while changing host, port or scheme is not.
    pub fn fingerprint(&self) -> String {
        format!("{}://{}:{}", self.scheme, self.host, self.port)
    }

    /// Human-readable label for a confirmation prompt. No key, no path.
    pub fn label(&self) -> String {
        let port_note = if self.port == if self.scheme == "https" { 443 } else { 80 } {
            String::new()
        } else {
            format!(":{}", self.port)
        };
        let warning = if self.insecure_local {
            " (local, unencrypted)"
        } else {
            ""
        };
        format!("{}://{}{}{}", self.scheme, self.host, port_note, warning)
    }
}

/// Loopback and private ranges, plus the names that mean "this machine".
///
/// Delegated rather than duplicated: the fetch tool needs the same answer for the
/// opposite reason, and two copies of an address rule drift until one of them is
/// wrong in the way that matters.
fn is_local_host(host: &str) -> bool {
    sunday_platform::is_local_host(host)
}

/// How a key is bound to an endpoint.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum KeyBinding {
    /// The key was confirmed for this fingerprint and may be sent.
    Confirmed,
    /// No key configured. Valid: a local model may not need one.
    Absent,
    /// A key exists but was confirmed for a different endpoint. It must not be
    /// sent until the user re-confirms.
    BoundToOther { confirmed_for: String },
}

/// What the caller must do before a request may carry the key.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AuthRequirement {
    Proceed,
    /// Prompt the user, then store the new binding.
    Reconfirm {
        previous: String,
        current: String,
    },
}

/// Decides whether the stored key may be sent to this endpoint.
pub fn authorization(
    endpoint: &Endpoint,
    key_present: bool,
    confirmed_for: Option<&str>,
) -> (KeyBinding, AuthRequirement) {
    if !key_present {
        return (KeyBinding::Absent, AuthRequirement::Proceed);
    }
    let current = endpoint.fingerprint();
    match confirmed_for {
        Some(confirmed) if confirmed == current => {
            (KeyBinding::Confirmed, AuthRequirement::Proceed)
        }
        Some(confirmed) => (
            KeyBinding::BoundToOther {
                confirmed_for: confirmed.to_owned(),
            },
            AuthRequirement::Reconfirm {
                previous: confirmed.to_owned(),
                current,
            },
        ),
        // A key with no recorded binding is the pre-binding upgrade case. Treat it
        // as unconfirmed rather than as consent: the user never approved an
        // endpoint for it.
        None => (
            KeyBinding::BoundToOther {
                confirmed_for: String::new(),
            },
            AuthRequirement::Reconfirm {
                previous: String::new(),
                current,
            },
        ),
    }
}

/// Removes a secret from text that may be logged, shown, or stored in an event.
///
/// Every place that reports an error or an event goes through this. It is not
/// defence in depth; it is the only thing standing between a provider's error body
/// and a transcript the user can scroll back through.
pub fn redact(text: &str, secret: &str) -> String {
    if secret.is_empty() || secret.len() < 4 {
        // Too short to redact meaningfully without mangling ordinary text.
        return text.to_owned();
    }
    text.replace(secret, "[redacted]")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strict() -> TransportPolicy {
        TransportPolicy::default()
    }

    fn permissive() -> TransportPolicy {
        TransportPolicy {
            allow_insecure_local: true,
        }
    }

    #[test]
    fn https_is_accepted_without_asking() {
        let endpoint = Endpoint::parse("https://api.openai.com/v1", strict()).unwrap();
        assert_eq!(endpoint.host(), "api.openai.com");
        assert_eq!(endpoint.fingerprint(), "https://api.openai.com:443");
        assert!(!endpoint.is_insecure_local());
    }

    #[test]
    fn plain_http_to_a_public_host_is_refused_even_with_opt_in() {
        // The opt-in is for local models, not for sending a key across the
        // internet in clear text.
        for policy in [strict(), permissive()] {
            let error = Endpoint::parse("http://api.openai.com/v1", policy).unwrap_err();
            assert!(
                matches!(error, EndpointError::PlainHttpRemote { .. }),
                "got {error:?}"
            );
        }
    }

    #[test]
    fn plain_http_to_localhost_needs_the_explicit_opt_in() {
        let error = Endpoint::parse("http://127.0.0.1:11434/v1", strict()).unwrap_err();
        assert!(
            matches!(error, EndpointError::PlainHttpNotAcknowledged { .. }),
            "a local http endpoint was accepted without acknowledgement: {error:?}"
        );
        let endpoint = Endpoint::parse("http://127.0.0.1:11434/v1", permissive()).unwrap();
        assert!(endpoint.is_insecure_local());
        assert!(endpoint.label().contains("unencrypted"));
    }

    #[test]
    fn private_ranges_and_the_emulator_route_count_as_local() {
        for host in ["10.0.2.2", "192.168.1.5", "172.16.0.1", "10.1.2.3"] {
            let url = format!("http://{host}:8080/v1");
            let endpoint = Endpoint::parse(&url, permissive())
                .unwrap_or_else(|e| panic!("{host} should be local: {e}"));
            assert!(endpoint.is_insecure_local());
        }
        // 172.32 is outside the private range.
        assert!(Endpoint::parse("http://172.32.0.1/v1", permissive()).is_err());
    }

    #[test]
    fn credentials_in_the_url_are_refused() {
        let error = Endpoint::parse("https://user:pass@api.openai.com/v1", strict()).unwrap_err();
        assert_eq!(error, EndpointError::EmbeddedCredentials);
    }

    #[test]
    fn a_query_or_fragment_is_refused() {
        assert!(matches!(
            Endpoint::parse("https://api.openai.com/v1?x=1", strict()).unwrap_err(),
            EndpointError::UnexpectedComponent(_)
        ));
        assert!(matches!(
            Endpoint::parse("https://api.openai.com/v1#frag", strict()).unwrap_err(),
            EndpointError::UnexpectedComponent(_)
        ));
    }

    #[test]
    fn non_http_schemes_are_refused() {
        for url in ["file:///etc/passwd", "ftp://x/y", "gopher://x"] {
            assert!(matches!(
                Endpoint::parse(url, permissive()).unwrap_err(),
                EndpointError::UnsupportedScheme(_)
            ));
        }
    }

    #[test]
    fn a_wildcard_host_is_refused() {
        assert!(matches!(
            Endpoint::parse("https://*.example.com/v1", strict()).unwrap_err(),
            EndpointError::BadHost(_)
        ));
    }

    #[test]
    fn a_key_confirmed_for_one_endpoint_is_not_sent_to_another() {
        let openai = Endpoint::parse("https://api.openai.com/v1", strict()).unwrap();
        let anthropic = Endpoint::parse("https://api.anthropic.com/v1", strict()).unwrap();

        let (binding, requirement) = authorization(&anthropic, true, Some(&openai.fingerprint()));
        assert!(
            matches!(binding, KeyBinding::BoundToOther { .. }),
            "a key bound to another host was sendable: {binding:?}"
        );
        match requirement {
            AuthRequirement::Reconfirm { previous, current } => {
                assert_eq!(previous, openai.fingerprint());
                assert_eq!(current, anthropic.fingerprint());
            }
            AuthRequirement::Proceed => panic!("a re-confirmation was not required"),
        }
    }

    #[test]
    fn the_same_host_on_another_port_is_a_different_binding() {
        let a = Endpoint::parse("https://api.example.com/v1", strict()).unwrap();
        let b = Endpoint::parse("https://api.example.com:8443/v1", strict()).unwrap();
        assert_ne!(a.fingerprint(), b.fingerprint());
        let (binding, _) = authorization(&b, true, Some(&a.fingerprint()));
        assert!(matches!(binding, KeyBinding::BoundToOther { .. }));
    }

    #[test]
    fn a_path_change_on_the_same_host_stays_authorised() {
        let v1 = Endpoint::parse("https://api.example.com/v1", strict()).unwrap();
        let v2 = Endpoint::parse("https://api.example.com/v2", strict()).unwrap();
        let (binding, requirement) = authorization(&v2, true, Some(&v1.fingerprint()));
        assert_eq!(binding, KeyBinding::Confirmed);
        assert_eq!(requirement, AuthRequirement::Proceed);
    }

    #[test]
    fn a_key_with_no_recorded_binding_is_not_consent() {
        let endpoint = Endpoint::parse("https://api.example.com/v1", strict()).unwrap();
        let (_, requirement) = authorization(&endpoint, true, None);
        assert!(
            matches!(requirement, AuthRequirement::Reconfirm { .. }),
            "an unbound key was treated as approved"
        );
    }

    #[test]
    fn no_key_needs_no_confirmation() {
        let endpoint = Endpoint::parse("http://127.0.0.1:11434/v1", permissive()).unwrap();
        let (binding, requirement) = authorization(&endpoint, false, None);
        assert_eq!(binding, KeyBinding::Absent);
        assert_eq!(requirement, AuthRequirement::Proceed);
    }

    #[test]
    fn redaction_removes_the_secret_and_leaves_the_rest() {
        let text = "provider rejected request with key sk-secret-123 for model x";
        assert_eq!(
            redact(text, "sk-secret-123"),
            "provider rejected request with key [redacted] for model x"
        );
        // A short or empty secret must not mangle ordinary text.
        assert_eq!(redact(text, ""), text);
        assert_eq!(redact(text, "sk"), text);
    }

    #[test]
    fn the_label_never_contains_the_path_or_a_secret() {
        let endpoint = Endpoint::parse("https://api.example.com/secret-path/v1", strict()).unwrap();
        let label = endpoint.label();
        assert!(!label.contains("secret-path"), "{label}");
        assert!(!label.contains("v1"), "{label}");
    }
}

// ---------------------------------------------------------------- binding

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;
use sunday_protocol::CoreError;

/// Which vendor a key belongs to.
///
/// The vendor is part of the binding because the same URL can mean different
/// things: `api.anthropic.com` speaks a different wire format from an
/// OpenAI-compatible server, and a key issued for one is not the other. Approving
/// one vendor must not approve the other at the same address.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Vendor {
    OpenAi,
    Anthropic,
    /// A self-hosted model server, or a third party that speaks the OpenAI wire
    /// format. This is the case where a key may legitimately be absent.
    Compatible,
}

impl Vendor {
    pub const ALL: [Self; 3] = [Self::OpenAi, Self::Anthropic, Self::Compatible];

    pub fn id(self) -> &'static str {
        match self {
            Self::OpenAi => "openai",
            Self::Anthropic => "anthropic",
            Self::Compatible => "openai-compatible",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "openai" => Some(Self::OpenAi),
            "anthropic" => Some(Self::Anthropic),
            // "custom" and "local" are how a user thinks about their own server.
            "openai-compatible" | "compatible" | "custom" | "local" => Some(Self::Compatible),
            _ => None,
        }
    }

    /// The hosted vendors always issue a key; a self-hosted server may not need one.
    pub fn key_required(self) -> bool {
        !matches!(self, Self::Compatible)
    }

    pub fn display_name(self) -> &'static str {
        match self {
            Self::OpenAi => "OpenAI",
            Self::Anthropic => "Anthropic",
            Self::Compatible => "openai-compatible endpoint",
        }
    }
}

pub const BINDINGS_FILE: &str = "provider.bindings.json";

/// Which endpoints each vendor's key has been approved for.
///
/// Holds vendor id to endpoint fingerprint, and nothing else. The key itself is in
/// the platform secret store, because a settings file gets copied, backed up and
/// attached to bug reports, and none of those should be a credential.
///
/// No digest of the key is stored either. The threat being closed is "the config
/// was edited so the key goes somewhere else", which the endpoint fingerprint
/// catches on its own; a digest would only tell us that the key changed, which is
/// something the user did on purpose.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProviderBook {
    /// vendor id -> endpoint fingerprint.
    #[serde(default)]
    approved: BTreeMap<String, String>,
}

impl ProviderBook {
    /// Reads the approvals for a data directory.
    ///
    /// A missing file means nothing has been approved. A corrupt file is read the
    /// same way on purpose: the safe reading of "I cannot tell what was approved"
    /// is "nothing was", which asks the user again instead of guessing. Returning
    /// an error would let a damaged file block startup, and trusting a partial
    /// parse would be worse than both.
    pub fn load(path: &Path) -> Self {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> Result<(), CoreError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| CoreError::storage(format!("binding dir: {e}")))?;
        }
        let text = serde_json::to_string_pretty(self)
            .map_err(|e| CoreError::storage(format!("binding encode: {e}")))?;
        crate::private_file::write(path, &text, "provider binding file")
    }

    pub fn approved_for(&self, vendor: Vendor) -> Option<&str> {
        self.approved.get(vendor.id()).map(String::as_str)
    }

    /// Records that the user approved this endpoint for this vendor. Writing the
    /// file is the caller's job, so a UI can approve several vendors at once.
    pub fn approve(&mut self, vendor: Vendor, endpoint: &Endpoint) {
        self.approved
            .insert(vendor.id().to_owned(), endpoint.fingerprint());
    }

    pub fn revoke(&mut self, vendor: Vendor) -> bool {
        self.approved.remove(vendor.id()).is_some()
    }
}

/// The decision for one startup, before any request is made.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Admission {
    /// The key is bound to this endpoint and may be sent.
    Clear { endpoint: Endpoint },
    /// No key configured, and this vendor does not need one.
    Keyless { endpoint: Endpoint },
    /// A key exists, but this (vendor, endpoint) pair was never approved.
    NeedsApproval {
        endpoint: Endpoint,
        /// The fingerprint it was approved for before, if any. Shown to the user so
        /// "it moved" and "it was never set" are distinguishable.
        approved_for: Option<String>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AdmissionError {
    Endpoint(EndpointError),
    /// A hosted vendor with no key is a misconfiguration, not a key-less mode.
    /// Reported separately so "no key" is never read as "cleared".
    KeyRequired {
        vendor: Vendor,
    },
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Endpoint(error) => write!(f, "{error}"),
            Self::KeyRequired { vendor } => write!(
                f,
                "{} needs an API key; only a self-hosted endpoint may run without one",
                vendor.display_name()
            ),
        }
    }
}

impl std::error::Error for AdmissionError {}

impl Admission {
    pub fn endpoint(&self) -> &Endpoint {
        match self {
            Self::Clear { endpoint }
            | Self::Keyless { endpoint }
            | Self::NeedsApproval { endpoint, .. } => endpoint,
        }
    }

    /// True only when a request carrying the key is allowed right now.
    pub fn is_cleared(&self) -> bool {
        matches!(self, Self::Clear { .. } | Self::Keyless { .. })
    }

    /// What to show the user when approval is needed. Contains endpoints, never a key.
    pub fn prompt(&self, vendor: Vendor) -> Option<String> {
        match self {
            Self::Clear { .. } | Self::Keyless { .. } => None,
            Self::NeedsApproval {
                endpoint,
                approved_for: Some(previous),
            } => Some(format!(
                "{} is configured for {}. Its API key was approved for {previous} instead, so it will not be sent \
                 until you approve this address.",
                vendor.display_name(),
                endpoint.label()
            )),
            Self::NeedsApproval {
                endpoint,
                approved_for: None,
            } => Some(format!(
                "Approve sending the {} API key to {}? It has not been approved for any endpoint yet.",
                vendor.display_name(),
                endpoint.label()
            )),
        }
    }
}

/// The single decision point: may this key be sent to this endpoint?
///
/// Order matters. The endpoint is validated before the binding is consulted, so an
/// insecure or malformed URL is refused outright and can never be "approved into"
/// existence by a stale binding. Built on `authorization` rather than reimplementing
/// it, so the binding rule has one definition.
pub fn admit(
    vendor: Vendor,
    raw_url: &str,
    key_present: bool,
    transport: TransportPolicy,
    book: &ProviderBook,
) -> Result<Admission, AdmissionError> {
    let endpoint = Endpoint::parse(raw_url, transport).map_err(AdmissionError::Endpoint)?;
    if vendor.key_required() && !key_present {
        return Err(AdmissionError::KeyRequired { vendor });
    }
    let (_, requirement) = authorization(&endpoint, key_present, book.approved_for(vendor));
    Ok(match requirement {
        AuthRequirement::Proceed if key_present => Admission::Clear { endpoint },
        AuthRequirement::Proceed => Admission::Keyless { endpoint },
        AuthRequirement::Reconfirm { previous, .. } => Admission::NeedsApproval {
            endpoint,
            approved_for: if previous.is_empty() {
                None
            } else {
                Some(previous)
            },
        },
    })
}

#[cfg(test)]
mod binding_tests {
    use super::*;

    fn strict() -> TransportPolicy {
        TransportPolicy::default()
    }

    fn openai_at(url: &str) -> Endpoint {
        Endpoint::parse(url, strict()).expect("endpoint")
    }

    const KEY: &str = "sk-live-9f3a2b7c4d5e6f80";

    /// The requirement in one test: editing the address must not move the key.
    #[test]
    fn a_tampered_address_does_not_carry_the_key_along() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join(BINDINGS_FILE);

        let mut book = ProviderBook::default();
        book.approve(Vendor::OpenAi, &openai_at("https://api.openai.com/v1"));
        book.save(&path).expect("save");

        // The attacker edits base_url in the config; the key is untouched.
        let reloaded = ProviderBook::load(&path);
        let admission = admit(
            Vendor::OpenAi,
            "https://collector.example.net/v1",
            true,
            strict(),
            &reloaded,
        )
        .expect("admission");

        assert!(
            !admission.is_cleared(),
            "a key approved for one host was cleared for another"
        );
        assert_eq!(
            admission.endpoint().fingerprint(),
            "https://collector.example.net:443"
        );
        match admission {
            Admission::NeedsApproval {
                approved_for: Some(previous),
                ..
            } => assert_eq!(previous, "https://api.openai.com:443"),
            other => panic!("expected a re-approval with the old host, got {other:?}"),
        }
    }

    /// Approving an endpoint for one vendor must not approve it for another: the
    /// same address serves two different wire formats and two different keys.
    #[test]
    fn approving_one_vendor_does_not_approve_another_at_the_same_address() {
        let mut book = ProviderBook::default();
        let shared = "https://gateway.example.com/v1";
        book.approve(Vendor::OpenAi, &openai_at(shared));

        let openai = admit(Vendor::OpenAi, shared, true, strict(), &book).expect("openai");
        assert!(openai.is_cleared());

        let anthropic = admit(Vendor::Anthropic, shared, true, strict(), &book).expect("anthropic");
        assert!(
            !anthropic.is_cleared(),
            "an OpenAI approval silently covered the Anthropic key as well"
        );
    }

    /// A binding file that cannot be read must fail closed, not open.
    #[test]
    fn a_damaged_binding_file_asks_again_instead_of_guessing() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join(BINDINGS_FILE);
        std::fs::write(&path, b"{ this is not json").expect("write");

        let book = ProviderBook::load(&path);
        let admission = admit(
            Vendor::OpenAi,
            "https://api.openai.com/v1",
            true,
            strict(),
            &book,
        )
        .expect("admission");
        assert!(
            !admission.is_cleared(),
            "a corrupt binding file was read as an approval"
        );
    }

    /// The binding file must not become a credential just because it is on disk.
    #[test]
    fn the_binding_file_holds_no_key() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join(BINDINGS_FILE);
        let mut book = ProviderBook::default();
        book.approve(Vendor::OpenAi, &openai_at("https://api.openai.com/v1"));
        book.save(&path).expect("save");

        let written = std::fs::read_to_string(&path).expect("read");
        assert!(
            !written.contains(KEY),
            "the binding file contains the API key: {written}"
        );
        assert!(
            written.contains("https://api.openai.com:443"),
            "the binding file does not record what was approved: {written}"
        );
    }

    /// An insecure URL is refused before the binding is even consulted, so no stale
    /// approval can keep a plain-HTTP endpoint alive.
    #[test]
    fn a_plain_http_endpoint_is_refused_even_when_it_was_approved_before() {
        let mut book = ProviderBook::default();
        // A public host over http cannot even be parsed into an endpoint, so the
        // book has no way to record it and no stale approval can keep it alive.
        assert!(Endpoint::parse(
            "http://api.openai.com/v1",
            TransportPolicy {
                allow_insecure_local: true,
            },
        )
        .is_err());
        book.approve(Vendor::OpenAi, &openai_at("https://api.openai.com/v1"));
        let refused = admit(
            Vendor::OpenAi,
            "http://api.openai.com/v1",
            true,
            TransportPolicy {
                allow_insecure_local: true,
            },
            &book,
        );
        assert!(
            matches!(
                refused,
                Err(AdmissionError::Endpoint(
                    EndpointError::PlainHttpRemote { .. }
                ))
            ),
            "plain http to a public host was not refused: {refused:?}"
        );
    }

    /// A hosted vendor with no key is a mistake, and must be reported as one rather
    /// than as "cleared".
    #[test]
    fn a_hosted_vendor_without_a_key_is_not_cleared() {
        let book = ProviderBook::default();
        let result = admit(
            Vendor::OpenAi,
            "https://api.openai.com/v1",
            false,
            strict(),
            &book,
        );
        assert!(
            matches!(result, Err(AdmissionError::KeyRequired { .. })),
            "a missing key was accepted: {result:?}"
        );
    }

    /// A local server with no key is legitimate: not every endpoint is a vendor.
    #[test]
    fn a_local_endpoint_without_a_key_is_allowed() {
        let book = ProviderBook::default();
        let admission = admit(
            Vendor::Compatible,
            "http://127.0.0.1:11434/v1",
            false,
            TransportPolicy {
                allow_insecure_local: true,
            },
            &book,
        )
        .expect("admission");
        assert!(matches!(admission, Admission::Keyless { .. }));
        assert!(admission.is_cleared());
        assert_eq!(admission.endpoint().base_url(), "http://127.0.0.1:11434/v1");
    }

    /// Relabelling the endpoint must not be enough to release the key.
    #[test]
    fn revoking_an_approval_puts_the_key_back_behind_the_prompt() {
        let mut book = ProviderBook::default();
        let endpoint = openai_at("https://api.openai.com/v1");
        book.approve(Vendor::OpenAi, &endpoint);
        assert!(admit(
            Vendor::OpenAi,
            "https://api.openai.com/v1",
            true,
            strict(),
            &book
        )
        .expect("admission")
        .is_cleared());

        assert!(book.revoke(Vendor::OpenAi));
        assert!(
            !admit(
                Vendor::OpenAi,
                "https://api.openai.com/v1",
                true,
                strict(),
                &book
            )
            .expect("admission")
            .is_cleared(),
            "revoking an approval did not stop the key from being sent"
        );
    }

    /// The prompt is user-facing text, so it must name the exact destination.
    #[test]
    fn the_prompt_names_the_destination_and_carries_no_secret() {
        let book = ProviderBook::default();
        let admission = admit(
            Vendor::Anthropic,
            "https://api.anthropic.com/v1",
            true,
            strict(),
            &book,
        )
        .expect("admission");
        let prompt = admission.prompt(Vendor::Anthropic).expect("a prompt");
        assert!(prompt.contains("api.anthropic.com"), "{prompt}");
        assert!(!prompt.contains(KEY), "{prompt}");
        assert!(
            !prompt.contains("/v1"),
            "the prompt leaks the path, which is not what is being approved: {prompt}"
        );
    }

    /// A custom port is a different destination, so it is a different binding.
    #[test]
    fn a_custom_port_is_a_different_destination() {
        let mut book = ProviderBook::default();
        book.approve(
            Vendor::Compatible,
            &openai_at("https://gateway.example.com/v1"),
        );
        let admission = admit(
            Vendor::Compatible,
            "https://gateway.example.com:8443/v1",
            true,
            strict(),
            &book,
        )
        .expect("admission");
        assert!(
            !admission.is_cleared(),
            "a different port reused the approval for the default port"
        );
    }
}
