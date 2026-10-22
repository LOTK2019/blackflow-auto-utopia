import traceback


def describe_error(exc):
    message = str(exc).strip() or "异常未提供文字说明，请查看完整错误日志"
    return f"{type(exc).__name__}: {message}"


def error_event(exc):
    return {"message": describe_error(exc), "error_type": type(exc).__name__,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))}
