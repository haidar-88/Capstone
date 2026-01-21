"""
Shared threading primitives for MVCCP Protocol.
Provides Read-Write Lock implementation for thread-safe table access.
"""
import threading


class RWLock:
    """
    Simple Read-Write Lock implementation using threading primitives.
    Allows multiple readers or one writer at a time.
    """
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
    
    def acquire_read(self):
        """Acquire read lock."""
        self._read_ready.acquire()
        try:
            self._readers += 1
        finally:
            self._read_ready.release()
    
    def release_read(self):
        """Release read lock."""
        self._read_ready.acquire()
        try:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()
        finally:
            self._read_ready.release()
    
    def acquire_write(self):
        """Acquire write lock."""
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()
    
    def release_write(self):
        """Release write lock."""
        self._read_ready.release()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass


class ReadLock:
    """Context manager for read lock."""
    def __init__(self, rwlock: RWLock):
        self.rwlock = rwlock
    
    def __enter__(self):
        self.rwlock.acquire_read()
        return self
    
    def __exit__(self, *args):
        self.rwlock.release_read()


class WriteLock:
    """Context manager for write lock."""
    def __init__(self, rwlock: RWLock):
        self.rwlock = rwlock
    
    def __enter__(self):
        self.rwlock.acquire_write()
        return self
    
    def __exit__(self, *args):
        self.rwlock.release_write()



