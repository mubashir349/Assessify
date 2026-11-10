"""Phase 10: work-email rules for institution signup.

- Free / personal email providers (Gmail, Yahoo, Outlook ...) are not work emails.
- An institution from the directory with a known domain: the admin's email must be on that domain (or a sub-domain,
  e.g. cs.neduet.edu.pk for neduet.edu.pk).
- Any other domain must have a mail server in DNS (MX record), so made-up domains are refused early.
"""
import logging

log = logging.getLogger(__name__)

FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in", "ymail.com", "rocketmail.com",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com", "windowslive.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "pm.me",
    "yandex.com", "yandex.ru", "mail.com", "gmx.com", "gmx.net", "zoho.com", "zohomail.com",
    "tutanota.com", "tuta.io", "rediffmail.com", "inbox.com", "fastmail.com", "hushmail.com",
    "mail.ru", "qq.com", "163.com", "126.com",
})


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in (email or "") else ""


def is_free(domain: str) -> bool:
    return domain.lower() in FREE_EMAIL_DOMAINS


def domain_list(expected: str | None) -> list[str]:
    """'comsats.edu.pk, cuilahore.edu.pk' -> ['comsats.edu.pk', 'cuilahore.edu.pk']"""
    return [d.strip().lower().lstrip("@") for d in (expected or "").split(",") if d.strip()]


def matches(domain: str, expected: str | None) -> bool:
    """neduet.edu.pk matches neduet.edu.pk and cs.neduet.edu.pk, never fakeneduet.edu.pk.
    expected may hold several domains separated by commas."""
    if not domain:
        return False
    domain = domain.lower()
    return any(domain == e or domain.endswith("." + e) for e in domain_list(expected))


def host_of(url: str | None) -> str:
    """https://www.neduet.edu.pk/about -> neduet.edu.pk"""
    if not url:
        return ""
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def accepts_mail(domain: str) -> bool | None:
    """True = the domain has a mail server, False = it surely has none, None = could not tell (no network / timeout).
    None never blocks a signup: the email code itself still has to arrive.
    A "no" is only trusted when DNS answers for a domain that surely has mail (gmail.com): some networks block or
    fake DNS, and then every domain would look dead."""
    result = _lookup(domain)
    if result is False and _lookup("gmail.com") is not True:
        log.warning("DNS looks blocked on this network: email domain check skipped for %s", domain)
        return None
    return result


def _lookup(domain: str) -> bool | None:
    try:
        import dns.exception
        import dns.resolver
    except ImportError:          # dnspython not installed: skip the check
        return None
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    try:
        answers = resolver.resolve(domain, "MX")
        return any(str(r.exchange).rstrip(".") for r in answers)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # no MX: a plain A record also receives mail by the email rules (RFC 5321), so check that once
        try:
            resolver.resolve(domain, "A")
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return False
        except dns.exception.DNSException:
            return None
    except dns.exception.DNSException as e:
        log.warning("MX lookup for %s failed: %s", domain, e.__class__.__name__)
        return None
