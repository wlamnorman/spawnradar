"""Authenticate against SpawnRadar and load-test a protected matches page."""

from __future__ import annotations

import argparse
import getpass
import math
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

DEFAULT_REQUESTS = 6
DEFAULT_CONCURRENCY = 2
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "spawnradar-matches-load-test/1.0"


@dataclass(frozen=True)
class RequestResult:
    """Result for one GET against the matches page."""

    index: int
    status_code: int | None
    elapsed_seconds: float
    final_url: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.devtools.matches_load_test",
        description=(
            "Log into SpawnRadar with the real form flow, verify a protected "
            "/matches page, then issue concurrent authenticated GET requests."
        ),
    )
    parser.add_argument(
        "--matches-url",
        default=os.environ.get("SR_MATCHES_URL", ""),
        help="Full protected matches URL to test.",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("SR_EMAIL", ""),
        help="Login email. Falls back to SR_EMAIL.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("SR_PASSWORD", ""),
        help=(
            "Login password. Falls back to SR_PASSWORD. If omitted, the script "
            "prompts securely."
        ),
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("SR_SESSION_ID", ""),
        help=(
            "Reuse an existing session_id cookie instead of logging in. "
            "Falls back to SR_SESSION_ID."
        ),
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=int(os.environ.get("SR_REQUESTS", DEFAULT_REQUESTS)),
        help=f"Total request count. Defaults to {DEFAULT_REQUESTS}.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("SR_CONCURRENCY", DEFAULT_CONCURRENCY)),
        help=f"Maximum in-flight requests. Defaults to {DEFAULT_CONCURRENCY}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("SR_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        help=(
            "Per-request timeout in seconds. "
            f"Defaults to {DEFAULT_TIMEOUT_SECONDS:.0f}."
        ),
    )
    return parser


def _extract_base_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Expected a full URL, got: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_csrf_token(html: str) -> str:
    tree = HTMLParser(html)
    field = tree.css_first('input[name="csrf_token"]')
    if field is None:
        raise ValueError("Login page did not include a csrf_token field.")
    token = (field.attributes.get("value") or "").strip()
    if not token:
        raise ValueError("Login page csrf_token field was empty.")
    return token


def _extract_error_message(html: str) -> str | None:
    tree = HTMLParser(html)
    field = tree.css_first(".alert.alert-error")
    if field is None:
        return None
    message = field.text(separator=" ", strip=True)
    return message or None


def _build_client(
    *, timeout_seconds: float, session_id: str | None = None
) -> httpx.Client:
    cookies = {"session_id": session_id} if session_id else None
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        cookies=cookies,
        headers={"user-agent": DEFAULT_USER_AGENT},
    )


def login_and_get_session_id(
    *,
    base_url: str,
    email: str,
    password: str,
    timeout_seconds: float,
) -> str:
    """Log in through the real HTML form flow and return the session_id."""
    login_url = f"{base_url}/auth/login"
    with _build_client(timeout_seconds=timeout_seconds) as client:
        login_page = client.get(login_url)
        login_page.raise_for_status()
        csrf_token = _extract_csrf_token(login_page.text)
        response = client.post(
            login_url,
            data={
                "email": email,
                "password": password,
                "csrf_token": csrf_token,
            },
        )
        if response.status_code >= 400:
            error = _extract_error_message(response.text)
            if error:
                raise RuntimeError(f"Login failed: {error}")
            response.raise_for_status()
        session_id = client.cookies.get("session_id")
        if not session_id:
            raise RuntimeError(
                "Login completed without setting a session_id cookie."
            )
        return session_id


def fetch_once(
    *,
    index: int,
    matches_url: str,
    session_id: str,
    timeout_seconds: float,
) -> RequestResult:
    """Issue one authenticated GET to the matches page."""
    started = time.perf_counter()
    try:
        with _build_client(
            timeout_seconds=timeout_seconds, session_id=session_id
        ) as client:
            response = client.get(matches_url)
        return RequestResult(
            index=index,
            status_code=response.status_code,
            elapsed_seconds=time.perf_counter() - started,
            final_url=str(response.url),
        )
    except httpx.HTTPError as exc:
        return RequestResult(
            index=index,
            status_code=None,
            elapsed_seconds=time.perf_counter() - started,
            final_url=matches_url,
            error=str(exc),
        )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return values[lower]
    fraction = rank - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def print_result(result: RequestResult) -> None:
    """Print one request result in a compact stable format."""
    if result.error:
        print(
            f"#{result.index:02d} ERROR {result.elapsed_seconds:.3f}s {result.error}"
        )
        return
    print(
        f"#{result.index:02d} {result.status_code} "
        f"{result.elapsed_seconds:.3f}s {result.final_url}"
    )


def print_summary(results: list[RequestResult], *, matches_url: str) -> None:
    """Print a small summary for the run."""
    durations = sorted(result.elapsed_seconds for result in results)
    success_count = sum(1 for result in results if result.ok)
    expected_url = matches_url.rstrip("/")
    wrong_target_count = sum(
        1
        for result in results
        if not result.error and result.final_url.rstrip("/") != expected_url
    )
    print()
    print("Summary")
    print(f"  ok={success_count}/{len(results)}")
    print(f"  min={durations[0]:.3f}s")
    print(f"  avg={statistics.fmean(durations):.3f}s")
    print(f"  p95={_percentile(durations, 0.95):.3f}s")
    print(f"  max={durations[-1]:.3f}s")
    print(f"  redirected_off_target={wrong_target_count}")


def run_requests(
    *,
    matches_url: str,
    session_id: str,
    total_requests: int,
    concurrency: int,
    timeout_seconds: float,
) -> list[RequestResult]:
    """Run the concurrent matches requests."""
    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                fetch_once,
                index=index,
                matches_url=matches_url,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
            )
            for index in range(1, total_requests + 1)
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print_result(result)
    return sorted(results, key=lambda result: result.index)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    if not args.matches_url:
        raise SystemExit("--matches-url is required.")
    if args.requests <= 0:
        raise SystemExit("--requests must be at least 1.")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be at least 1.")

    base_url = _extract_base_url(args.matches_url)
    session_id = args.session_id.strip()
    if not session_id:
        email = args.email.strip()
        if not email:
            raise SystemExit(
                "--email is required when --session-id is omitted."
            )
        password = args.password or getpass.getpass(
            prompt=f"Password for {email}: "
        )
        session_id = login_and_get_session_id(
            base_url=base_url,
            email=email,
            password=password,
            timeout_seconds=args.timeout,
        )
        print(f"Authenticated at {base_url} as {email}.")
    else:
        print(f"Reusing session_id against {base_url}.")

    verification = fetch_once(
        index=0,
        matches_url=args.matches_url,
        session_id=session_id,
        timeout_seconds=args.timeout,
    )
    print("Verification")
    print_result(verification)
    if not verification.ok:
        print("Verification failed. Aborting load test.", file=sys.stderr)
        return 1
    if verification.final_url.rstrip("/") != args.matches_url.rstrip("/"):
        print(
            "Verification redirected away from the requested matches page. "
            "Aborting load test.",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        f"Running {args.requests} requests with concurrency {args.concurrency}..."
    )
    results = run_requests(
        matches_url=args.matches_url,
        session_id=session_id,
        total_requests=args.requests,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout,
    )
    print_summary(results, matches_url=args.matches_url)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
