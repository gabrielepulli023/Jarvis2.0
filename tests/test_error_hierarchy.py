import builtins,unittest
from jarvis_core.errors import BrokerError,JarvisError,PermissionError,RecoveryError,ToolError,VerificationError,VoiceError

class ErrorHierarchyTests(unittest.TestCase):
    def test_named_errors_share_base_and_permission_remains_builtin_compatible(self):
        for error in (BrokerError,PermissionError,RecoveryError,ToolError,VerificationError,VoiceError):self.assertTrue(issubclass(error,JarvisError))
        self.assertTrue(issubclass(PermissionError,builtins.PermissionError))

if __name__=="__main__":unittest.main()
