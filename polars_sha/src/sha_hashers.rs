use sha2::{Digest, Sha256, Sha512};
use std::fmt::Write;

pub fn sha2_256_hash(value: &str, output: &mut String) {
    let hash = Sha256::digest(value);
    write!(output, "{:x}", hash).unwrap()
}

pub fn sha2_512_hash(value: &str, output: &mut String) {
    let hash = Sha512::digest(value);
    write!(output, "{:x}", hash).unwrap()
}
