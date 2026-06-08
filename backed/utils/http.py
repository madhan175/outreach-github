import requests


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}")


class RateLimitError(APIError):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(status, message)
        # retry_after in seconds when provided by the server (Retry-After header)
        self.retry_after = retry_after


def post(url: str, headers: dict, payload: dict, context: str = "") -> dict:
    """
    Simple HTTP POST helper.
    Raises APIError on non-200 responses.
    Returns JSON response.
    """

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code == 429:
            # Prefer the server-supplied Retry-After header when available
            retry_after = None
            try:
                ra = response.headers.get("Retry-After")
                if ra is not None:
                    # some servers return float/int, others use HTTP-date; try numeric first
                    try:
                        retry_after = int(float(ra))
                    except Exception:
                        retry_after = None
            except Exception:
                retry_after = None

            raise RateLimitError(
                429,
                f"{context}: Rate limit exceeded",
                retry_after=retry_after,
            )

        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text

            raise APIError(
                response.status_code,
                f"{context}: {detail}"
            )

        return response.json()

    except requests.RequestException as e:
        raise APIError(500, f"{context}: {str(e)}")