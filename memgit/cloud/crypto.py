"""Client-side crypto for memgit cloud — the PyNaCl half of docs/PROTOCOL.md (memgit-cloud repo).

The browser client (libsodium-wrappers) mirrors these exact constructions; KDF params are
pinned explicitly so both sides agree byte-for-byte. The server only ever sees the outputs
marked "wire" — never a passphrase, master key, enc key, private key, or team key.
"""
from __future__ import annotations

import base64

from nacl import pwhash, utils
from nacl.bindings import (
    crypto_box_seal,
    crypto_box_seal_open,
    crypto_generichash_blake2b_salt_personal as _blake2b,
)
from nacl.public import PrivateKey
from nacl.secret import SecretBox

ARGON2_OPSLIMIT = 3
ARGON2_MEMLIMIT = 64 * 1024 * 1024  # 64 MiB


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def derive(key: bytes, context: bytes) -> bytes:
    """32-byte keyed-BLAKE2b subkey derivation (matches crypto_generichash in JS)."""
    return _blake2b(context, digest_size=32, key=key)


def secretbox(message: bytes, key: bytes) -> str:
    nonce = utils.random(SecretBox.NONCE_SIZE)
    return b64u(nonce + SecretBox(key).encrypt(message, nonce).ciphertext)


def secretbox_open(data: str, key: bytes) -> bytes:
    raw = b64u_decode(data)
    return SecretBox(key).decrypt(raw[SecretBox.NONCE_SIZE:], raw[:SecretBox.NONCE_SIZE])


def master_key(passphrase: str, kdf_salt: bytes) -> bytes:
    return pwhash.argon2id.kdf(
        32, passphrase.encode('utf-8'), kdf_salt,
        opslimit=ARGON2_OPSLIMIT, memlimit=ARGON2_MEMLIMIT,
    )


def auth_key(mk: bytes) -> str:  # wire
    return b64u(derive(mk, b'memgit-cloud/auth/v1'))


def enc_key(mk: bytes) -> bytes:
    return derive(mk, b'memgit-cloud/enc/v1')


def new_keypair() -> PrivateKey:
    return PrivateKey.generate()


def seal(message: bytes, public_key: bytes) -> str:  # wire
    return b64u(crypto_box_seal(message, public_key))


def seal_open(data: str, public_key: bytes, private_key: bytes) -> bytes:
    return crypto_box_seal_open(b64u_decode(data), public_key, private_key)


# ── team-key derivations ─────────────────────────────────────────────────────

def meta_key(team_key: bytes) -> bytes:
    return derive(team_key, b'memgit-cloud/meta/v1')


def obj_enc_key(team_key: bytes) -> bytes:
    return derive(team_key, b'memgit-cloud/objenc/v1')


def obj_id_key(team_key: bytes) -> bytes:
    return derive(team_key, b'memgit-cloud/objid/v1')


def remote_id(team_key: bytes, name: str) -> str:
    """Opaque server-side id for an object SHA or a ref/thread name."""
    return derive(obj_id_key(team_key), name.encode('utf-8')).hex()


def encrypt_meta(team_key: bytes, text: str) -> str:  # wire
    return secretbox(text.encode('utf-8'), meta_key(team_key))


def decrypt_meta(team_key: bytes, data: str) -> str:
    return secretbox_open(data, meta_key(team_key)).decode('utf-8')


def encrypt_object(team_key: bytes, sha_hex: str, raw: bytes) -> str:  # wire
    return secretbox(sha_hex.encode('ascii') + raw, obj_enc_key(team_key))


def decrypt_object(team_key: bytes, data: str) -> tuple[str, bytes]:
    envelope = secretbox_open(data, obj_enc_key(team_key))
    return envelope[:64].decode('ascii'), envelope[64:]


# ── invites ──────────────────────────────────────────────────────────────────

def invite_material(team_key: bytes) -> tuple[str, str, str]:
    """Returns (secret_b64u_for_url_fragment, box_wire, verifier_wire)."""
    secret = utils.random(32)
    ikey = derive(secret, b'memgit-cloud/invite/v1')
    verifier = derive(secret, b'memgit-cloud/invite-verifier/v1').hex()
    return b64u(secret), secretbox(team_key, ikey), verifier


def invite_open(secret_b64u: str, box: str) -> tuple[bytes, str]:
    """Returns (team_key, verifier) from a link fragment secret + server box."""
    secret = b64u_decode(secret_b64u)
    ikey = derive(secret, b'memgit-cloud/invite/v1')
    verifier = derive(secret, b'memgit-cloud/invite-verifier/v1').hex()
    return secretbox_open(box, ikey), verifier


def invite_verifier(secret_b64u: str) -> str:
    return derive(b64u_decode(secret_b64u), b'memgit-cloud/invite-verifier/v1').hex()
