# Security Policy

## Supported versions

Security fixes target the latest stable release and current `main`. Older
releases may be investigated, but users should upgrade to the latest stable
version.

## Reporting a vulnerability

Please do **not** disclose suspected vulnerabilities in a public issue,
discussion, pull request, or Lichess chat.

Use GitHub's private vulnerability-reporting form:

<https://github.com/SahilKDas/Eloi/security/advisories/new>

Include the affected version or commit, operating system, reproduction steps,
impact, and any proof of concept that can be shared safely. Remove API tokens,
credentials, private configuration, and unrelated personal data.

The maintainer will acknowledge a usable report when practical, investigate
it, and coordinate disclosure after a fix or mitigation is available. Please
allow reasonable time for that process before publishing details.

## Particularly sensitive areas

- Lichess bearer-token handling and configuration parsing;
- network endpoint validation and WinHTTP streaming;
- archive extraction or package contents;
- untrusted FEN, PGN, EPD, UCI, and engine output parsing;
- child-process containment and command construction;
- bundled third-party code, models, and DLLs.

Ordinary engine crashes, weak chess moves, strength regressions, and incorrect
evaluations are bugs rather than security vulnerabilities unless they cross a
security boundary or enable denial of service beyond the local chess process.
