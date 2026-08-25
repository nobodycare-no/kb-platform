"""业务异常：由全局异常处理器转换为统一响应包。"""


class ApiError(Exception):
    def __init__(self, status_code: int, code: int, message: str, data=None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)
