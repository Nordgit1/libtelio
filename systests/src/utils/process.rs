use std::process::{Command, ExitStatus};

#[derive(Debug)]
pub enum ProcessExecError {
    FailedToRun(std::io::Error),
    FailedDuringRun(ExitStatus, String),
}

pub fn run_command(args: &[&str]) -> Result<String, ProcessExecError> {
    let full_command = args.join(" ");
    let res = Command::new(args[0])
        .args(&args[1..])
        .output()
        .map_err(ProcessExecError::FailedToRun)?;
    if res.status.success() {
        println!("Successfully executed '{full_command}'");
        Ok(String::from_utf8(res.stdout).expect("Command output should be valid utf8 string"))
    } else {
        let err = ProcessExecError::FailedDuringRun(
            res.status,
            String::from_utf8(res.stderr).expect("Command output shhould be valid utf8 string"),
        );
        println!("Failed to execute '{full_command}' with error {err:?}");
        Err(err)
    }
}
