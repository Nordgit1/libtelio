use std::{io::Write, sync::Arc};

#[derive(Default)]
struct IoWrapper {
    buffer: Vec<String>,
}

impl Write for IoWrapper {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        let s = String::from_utf8_lossy(buf).to_string();
        self.buffer.push(s);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

struct TestFailure {
    error: String,
    stdout: Vec<String>,
}

pub fn test_runner<F>(test_fn: F) -> Result<(), TestFailure>
where
    F: Fn(),
{
    let io_wrapper = Arc::new(IoWrapper::default());
    let wrapper = io_wrapper.clone();
    let handle = std::thread::spawn(move || {
        let _ = std::io::set_print(Some(wrapper));
        test_fn();
    });
    Ok(())
}
