#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, State};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, Serialize, Deserialize)]
struct Conn {
    #[serde(rename = "baseUrl", default)]
    base_url: String,
    token: String,
    #[serde(default)]
    port: u16,
}

type Ready = Arc<(Mutex<Option<Result<Conn, String>>>, Condvar)>;

struct Backend {
    child: Mutex<Option<Child>>,
    ready: Ready,
}

fn start_backend() -> Backend {
    let ready: Ready = Arc::new((Mutex::new(None), Condvar::new()));
    let publish = {
        let ready = ready.clone();
        move |r: Result<Conn, String>| {
            *ready.0.lock().unwrap() = Some(r);
            ready.1.notify_all();
        }
    };

    // sidecar 与应用 EXE 位于同一目录（开发与安装包均如此）。
    let exe = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join("edge-tts-backend.exe")));
    let spawned = exe.ok_or_else(|| "无法定位后端程序".to_string()).and_then(|exe| {
        let mut command = Command::new(&exe);
        if let Ok(data_dir) = std::env::var("EDGE_TTS_DATA_DIR") {
            command.args(["--data-dir", &data_dir]);
        }
        command
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .stdin(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("后端启动失败：{e}"))
    });

    let mut child = match spawned {
        Ok(c) => c,
        Err(e) => {
            publish(Err(e));
            return Backend { child: Mutex::new(None), ready };
        }
    };
    let stdout = child.stdout.take().unwrap();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&line) {
                if v["event"] == "ready" {
                    let port = v["port"].as_u64().unwrap_or(0) as u16;
                    publish(Ok(Conn {
                        base_url: format!("http://127.0.0.1:{port}"),
                        token: v["token"].as_str().unwrap_or_default().to_string(),
                        port,
                    }));
                }
            }
        }
        // 管道关闭仍未 ready：后端已退出。
        publish(Err("后端进程意外退出（可能已有另一个实例在使用同一数据目录）".into()));
    });
    Backend { child: Mutex::new(Some(child)), ready }
}

#[tauri::command]
async fn get_conn(state: State<'_, Backend>) -> Result<Conn, String> {
    let ready = state.ready.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let (lock, cv) = &*ready;
        let guard = lock.lock().unwrap();
        let (guard, _) = cv
            .wait_timeout_while(guard, Duration::from_secs(60), |r| r.is_none())
            .unwrap();
        guard.clone().unwrap_or_else(|| Err("后端启动超时".into()))
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 带令牌请求后端正常关闭，等待退出；超时则终止整个进程树（单文件 EXE 有外层与内部两个进程）。
fn stop_backend(backend: &Backend) {
    let Some(mut child) = backend.child.lock().unwrap().take() else { return };
    if let Some(Ok(conn)) = backend.ready.0.lock().unwrap().clone() {
        if let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], conn.port).into(), Duration::from_secs(2)) {
            let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
            let req = format!(
                "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                conn.token
            );
            if s.write_all(req.as_bytes()).is_ok() {
                let mut sink = Vec::new();
                let _ = s.read_to_end(&mut sink);
            }
        }
    }
    for _ in 0..80 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = Command::new("taskkill")
        .args(["/T", "/F", "/PID", &child.id().to_string()])
        .creation_flags(CREATE_NO_WINDOW)
        .status();
}

fn main() {
    let app = tauri::Builder::default()
        // 单实例插件必须最先注册：再次启动时把已有窗口带到前台，而不是再起一个后端。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(start_backend());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_conn])
        .build(tauri::generate_context!())
        .expect("应用构建失败");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(backend) = handle.try_state::<Backend>() {
                stop_backend(&backend);
            }
        }
    });
}
