//! Reproduces the "idle RPC bridge dies after a while" report.
//!
//! The bridge in `rpc.rs` splits the WebSocket into a reader and a writer. The reader
//! keeps polling, the writer only writes when a call is made. This probe does exactly
//! that and prints every frame with a timestamp, so a keepalive problem shows up as a
//! close around the server's ping interval.
//!
//!     cargo run --example idle_probe -- ws://127.0.0.1:59928/api/core/app-server 60

use futures_util::{SinkExt, StreamExt};
use std::time::{Duration, Instant};
use tokio_tungstenite::tungstenite::Message;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let url = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "ws://127.0.0.1:59928/api/core/app-server".to_owned());
    let seconds: u64 = std::env::args()
        .nth(2)
        .and_then(|value| value.parse().ok())
        .unwrap_or(60);
    let (socket, _) = tokio_tungstenite::connect_async(url.as_str()).await?;
    let start = Instant::now();
    // No type annotation: the split halves are only used through their traits, and
    // naming the concrete stream type would pin this probe to one backend.
    let (mut sink, mut stream) = socket.split();
    sink.send(Message::Text(
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": { "clientInfo": { "name": "idle-probe", "version": "0" } },
        })
        .to_string()
        .into(),
    ))
    .await?;

    let deadline = tokio::time::sleep(Duration::from_secs(seconds));
    tokio::pin!(deadline);
    loop {
        tokio::select! {
            message = stream.next() => match message {
                Some(Ok(Message::Text(text))) => {
                    println!("{:>6.1}s text {}B", start.elapsed().as_secs_f64(), text.len());
                }
                Some(Ok(other)) => {
                    println!("{:>6.1}s other {other:?}", start.elapsed().as_secs_f64());
                }
                Some(Err(error)) => {
                    println!("{:>6.1}s ERROR {error:?}", start.elapsed().as_secs_f64());
                    return Ok(());
                }
                None => {
                    println!("{:>6.1}s CLOSED by peer", start.elapsed().as_secs_f64());
                    return Ok(());
                }
            },
            _ = &mut deadline => {
                println!("{:>6.1}s still open after {seconds}s", start.elapsed().as_secs_f64());
                return Ok(());
            }
        }
    }
}
