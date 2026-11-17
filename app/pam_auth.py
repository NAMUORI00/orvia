"""Linux PAM authentication; credentials exist only during this call."""
import ctypes as C
import ctypes.util

class Message(C.Structure):
    _fields_ = [("style", C.c_int), ("msg", C.c_char_p)]
class Response(C.Structure):
    _fields_ = [("resp", C.c_void_p), ("code", C.c_int)]
CALLBACK = C.CFUNCTYPE(C.c_int, C.c_int, C.POINTER(C.POINTER(Message)), C.POINTER(C.POINTER(Response)), C.c_void_p)
class Conversation(C.Structure):
    _fields_ = [("conv", CALLBACK), ("data", C.c_void_p)]

def authenticate(username, password=None):
    pam=C.CDLL(ctypes.util.find_library("pam"));libc=C.CDLL(ctypes.util.find_library("c"))
    libc.calloc.argtypes=[C.c_size_t,C.c_size_t];libc.calloc.restype=C.c_void_p
    libc.strdup.argtypes=[C.c_char_p];libc.strdup.restype=C.c_void_p
    libc.free.argtypes=[C.c_void_p]
    @CALLBACK
    def conv(n,msg,out,data):
        if n<1 or n>32: return 19
        ptr=libc.calloc(n,C.sizeof(Response));arr=C.cast(ptr,C.POINTER(Response))
        for i in range(n):
            style=msg[i].contents.style
            if style in (1,2):
                if password is None:
                    for j in range(i): libc.free(arr[j].resp)
                    libc.free(ptr);return 19
                arr[i].resp=libc.strdup((password if style==1 else username).encode())
            elif style not in (3,4):
                for j in range(i): libc.free(arr[j].resp)
                libc.free(ptr);return 19
        out[0]=arr;return 0
    handle=C.c_void_p();conversation=Conversation(conv,None)
    pam.pam_start.argtypes=[C.c_char_p,C.c_char_p,C.POINTER(Conversation),C.POINTER(C.c_void_p)]
    for name in ['pam_authenticate','pam_acct_mgmt','pam_end']:
        getattr(pam,name).argtypes=[C.c_void_p,C.c_int]
    status=pam.pam_start(b'orvia',username.encode(),C.byref(conversation),C.byref(handle))
    if status: return False
    try:
        if password is not None:
            status=pam.pam_authenticate(handle,1)
            if status: return False
        status=pam.pam_acct_mgmt(handle,0)
        return status==0
    finally: pam.pam_end(handle,status)
