use sp1_build::{build_program_with_args, BuildArgs};

fn main() {
    println!("cargo:rerun-if-env-changed=SP1_DOCKER");
    let mut args = BuildArgs::default();
    if std::env::var("SP1_DOCKER").unwrap_or_default() == "true" {
        args.docker = true;
    }
    build_program_with_args("../program", args)
}
