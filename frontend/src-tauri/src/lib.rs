use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8765;

struct BackendProcess(Mutex<Option<Child>>);

/// 解析 Python 后端目录：环境变量 > 开发目录（含 .venv）> 打包资源目录。
fn resolve_backend_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("MULTI_AI_BACKEND_DIR") {
        let path = PathBuf::from(dir);
        if path.join("app").is_dir() {
            return Some(path);
        }
    }
    // 开发模式：src-tauri -> frontend -> 项目根（此目录带 .venv）
    let dev = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("backend"));
    if let Some(path) = dev.filter(|p| p.join("app").is_dir()) {
        return Some(path);
    }
    if let Ok(resource) = app.path().resource_dir() {
        let path = resource.join("backend");
        if path.join("app").is_dir() {
            return Some(path);
        }
        let nested = resource.join("_up_").join("_up_").join("backend");
        if nested.join("app").is_dir() {
            return Some(nested);
        }
    }
    None
}

fn resolve_python(backend: &Path) -> PathBuf {
    if let Ok(exe) = std::env::var("MULTI_AI_PYTHON") {
        return PathBuf::from(exe);
    }
    let venv = backend.join(".venv").join("Scripts").join("python.exe");
    if venv.is_file() {
        return venv;
    }
    let unix_venv = backend.join(".venv").join("bin").join("python");
    if unix_venv.is_file() {
        return unix_venv;
    }
    PathBuf::from("python")
}

fn backend_alive() -> bool {
    let addr: SocketAddr = format!("{BACKEND_HOST}:{BACKEND_PORT}").parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn log_line(msg: &str) {
    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(std::env::temp_dir().join("multi-ai-group-backend.log"))
        .and_then(|mut file| {
            use std::io::Write;
            writeln!(file, "{msg}")
        });
}

fn spawn_backend(app: &tauri::AppHandle) -> Option<Child> {
    if backend_alive() {
        log_line("已有后端在运行，跳过启动");
        return None;
    }
    let Some(backend) = resolve_backend_dir(app) else {
        log_line("未找到 backend 目录");
        return None;
    };
    let python = resolve_python(&backend);
    log_line(&format!("backend={backend:?} python={python:?}"));
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("app.main")
        .current_dir(&backend)
        .env("MULTI_AI_HOST", BACKEND_HOST)
        .env("MULTI_AI_PORT", BACKEND_PORT.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null());
    let log_path = std::env::temp_dir().join("multi-ai-group-backend.log");
    if let Ok(file) = std::fs::OpenOptions::new().create(true).append(true).open(&log_path) {
        command.stderr(Stdio::from(file));
    } else {
        command.stderr(Stdio::null());
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    match command.spawn() {
        Ok(child) => {
            log_line(&format!("后端已启动 pid={}", child.id()));
            Some(child)
        }
        Err(err) => {
            log_line(&format!("启动 Python 后端失败：{err}"));
            None
        }
    }
}

fn kill_backend(app: &tauri::AppHandle) {
    let state = app.state::<BackendProcess>();
    let mut guard = match state.0.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let child = spawn_backend(app.handle());
            app.manage(BackendProcess(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_backend(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("Tauri 初始化失败")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                kill_backend(app_handle);
            }
        });
}
