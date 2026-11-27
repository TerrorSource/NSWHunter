"""The panel over HTTPS, if the settings ask for it.

With a certificate of your own (a PEM file, and its key), or else with one NSWHunter makes
itself. Nobody vouches for a self-made certificate, so the browser warns about it once; the
connection is encrypted all the same."""
import datetime
import ipaddress
import os
import ssl

import config

CERT_DIR = os.path.join(config.DATA_DIR, "certs")
OWN_CERT = os.path.join(CERT_DIR, "nswhunter.crt")
OWN_KEY = os.path.join(CERT_DIR, "nswhunter.key")
VALID_DAYS = 800  # browsers refuse a certificate that lasts much longer
RENEW_DAYS = 30


class TlsError(Exception):
    pass


def self_made(now=None):
    """Make a certificate of our own if there is none, or the one there ends within a month.
    Returns True if a new one was made."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        with open(OWN_CERT, "rb") as f:
            old = x509.load_pem_x509_certificate(f.read())
        if os.path.isfile(OWN_KEY) and old.not_valid_after_utc - now > datetime.timedelta(days=RENEW_DAYS):
            return False
    except (OSError, ValueError):
        pass
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NSWHunter")])
    # The names the panel is opened by: this machine itself, and the host names of the settings.
    names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    names += [x509.DNSName(host) for host in sorted(config.panel_hosts())]
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
                   .add_extension(x509.SubjectAlternativeName(names), critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    os.makedirs(CERT_DIR, mode=0o700, exist_ok=True)
    # The key is for the app user only.
    with os.fdopen(os.open(OWN_KEY, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(OWN_CERT, "wb") as f:
        f.write(certificate.public_bytes(serialization.Encoding.PEM))
    return True


def files(cfg=config):
    """(certificate, key, is it the self-made one) as the settings have them."""
    if cfg.SSL_CERT_PATH:
        # Without a key of its own, the key is in the file of the certificate.
        return cfg.SSL_CERT_PATH, cfg.SSL_KEY_PATH or cfg.SSL_CERT_PATH, False
    return OWN_CERT, OWN_KEY, True


def context(cfg=config):
    """What the HTTPS side of the panel listens with. TlsError with a text for the user if the
    certificate or its key cannot be used."""
    certificate, key, own = files(cfg)
    try:
        if own:
            self_made()
        made = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        made.minimum_version = ssl.TLSVersion.TLSv1_2
        made.load_cert_chain(certificate, key)
    except FileNotFoundError as e:
        raise TlsError(f"{e.filename or certificate} is not there. Is it in a volume of the container?") from e
    except PermissionError as e:
        raise TlsError(f"{e.filename or certificate} cannot be read by NSWHunter") from e
    except (OSError, ssl.SSLError, ValueError) as e:
        raise TlsError(f"the certificate and its key cannot be used: {getattr(e, 'reason', None) or e}") from e
    return made
