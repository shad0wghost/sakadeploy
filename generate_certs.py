import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def generate_self_signed_cert(cert_dir: Path):
    """Generates a self-signed SSL certificate and key."""
    # Generate our key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Create a self-signed certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(x509.NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, u"Anywhere"),
        x509.NameAttribute(x509.NameOID.LOCALITY_NAME, u"Some City"),
        x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, u"Self-Signed CICD"),
        x509.NameAttribute(x509.NameOID.COMMON_NAME, u"localhost"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)  # Valid for 1 year
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    ).sign(key, hashes.SHA256(), default_backend())

    # Write our certificate and key
    cert_dir.mkdir(parents=True, exist_ok=True)
    with open(cert_dir / "cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(cert_dir / "key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

if __name__ == "__main__":
    certs_path = Path("certs")
    generate_self_signed_cert(certs_path)
    print(f"Self-signed certificate and key generated in {certs_path.absolute()}")
