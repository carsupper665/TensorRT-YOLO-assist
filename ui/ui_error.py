#ui/ui_error.py
class TensorRTWheelNotFound(Exception):
    def __init__(self, message="No compatible TensorRT wheel found in the specified directory. Please download the appropriate wheel from NVIDIA's official site and place it in the 'packages' folder.\n Or install manually."):
        self.message = message
        super().__init__(self.message)

class UnexpectedError(Exception):
    def __init__(self, message="An unexpected error occurred. Please try reinstalling the application or contact support if the issue persists."):
        self.message = message
        super().__init__(self.message)