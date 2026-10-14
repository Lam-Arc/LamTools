# Pairing and relay trust boundary

This describes the implemented six-digit compatibility flow, not a zero-trust
or password-authenticated key exchange (PAKE) protocol.

## Complete flow

1. Desktop creates one cryptographically random six-digit code, a random
   pairing ID, and a five-minute expiry. Creating another code invalidates the
   previous session. Existing trusted devices retain their credentials.
2. LAN/manual resolution posts the code to `/_lamtools/pairing/resolve` and
   receives the desktop ID/key, gateway address, pairing ID and expiry. This
   endpoint is bootstrap metadata, not an authenticated channel. A plain HTTP
   LAN connection exposes its request code to network observers.
3. For existing WAN relay pairing, desktop sends `pairing_register` over WSS.
   The relay reads the code and public metadata into its ephemeral directory.
   The client uses its existing node-bound session to resolve the code over
   HTTPS and obtain a short-lived one-time pairing ticket. Local/manual pairing
   has no account dependency; no new account system was introduced.
4. The client opens the direct gateway or ticket-authorized relay route and
   runs Noise XX. It checks the responder static key against the bootstrap key
   **before** sending the code in handshake message three. This protects against
   a different key on the chosen route, but trusts the source of that bootstrap
   key. HTTP discovery and the relay directory are not out-of-band key proofs.
5. Desktop verifies the code and expiry atomically, consumes the pairing
   session, binds the actual Noise mobile static key to the device ID, and
   persists an independent random access token through the secure store. The
   token response is encrypted. The client checks returned desktop ID/key before
   saving trust. A ticket alone cannot redeem a code or enroll a device.
6. Direct reconnect authenticates the stored device ID, token and Noise static
   key. The existing account-authorized relay path uses a node/workspace ticket
   and a process-private loopback capability; it is a separate authorization
   path. Neither reconnect requires a new pairing code. Relay host replacement
   closes attached mobile tunnels; routing is reselected on reconnect.

## Guessing and resource boundaries

- Desktop resolution and redemption share **five failed code comparisons per
  pairing session**, including attempts from other sockets. Counters and
  single-use consumption use the same write lock. Exhaustion prevents even the
  correct code from enrolling a device until a new session is created. Used
  and locked sessions remain unavailable across reconnects.
- Relay resolution admits **five requests per existing account per five-minute
  window**, and **50 requests globally per process per window**. Correct,
  incorrect, expired and malformed-but-parsed authenticated requests count.
  Node/session-token changes and socket reconnects do not reset account limits.
  The bounded table and mutex make parallel admission atomic; forwarding
  headers never select a budget. Excess requests return 429/Retry-After: 300.
- Relay registrations must belong to the current desktop socket, cannot take
  another desktop's pairing ID, and expire within six minutes of relay time
  (allowing one minute of clock skew for the desktop's five-minute TTL).
- Limits are process-local, not durable or distributed. An operator restart
  resets relay lookup budgets; deploying replicas requires shared state.

## Compatibility and remaining risks

The six-digit input, JSON fields and Noise v1 framing remain unchanged. New
failure modes are 429/lockout and rejection of plaintext public relay URLs
by the desktop relay client and Core CLI account login path.
Upgrade the desktop and relay to enforce both limits. Old clients remain wire
compatible, but only upgraded clients enforce the public-relay TLS requirement.

The relay sees codes and routing metadata; a malicious relay can substitute
bootstrap identity data or abuse knowledge of active codes. TLS protects
against network observers, not the relay operator. Hashing a six-digit code
would not solve this: its million-value space is enumerable. Keeping it secret
from the relay requires a different WAN bootstrap/PAKE or an out-of-band
high-entropy invitation/key, beyond this compatibility patch.

Use trusted LAN/VPN routes for the existing HTTP bootstrap. Noise protects
redeem messages, credentials and application traffic, but cannot retroactively
protect the earlier HTTP request or independently authenticate its metadata.
Neither passive code exposure nor active bootstrap substitution on an
untrusted LAN is eliminated by attempt limits. This is a remaining exposure.

An attacker can exhaust a displayed code's failure budget or the relay's global
window to deny pairing temporarily. Regenerate a locked desktop code; respect
relay Retry-After. Limit registration/control-plane exposure at the TLS proxy
and firewall. Do not log code/request bodies or store them in operational logs.
