class SingletonMeta(type):
    """Singleton metaclass — each subclass gets its own instance."""
    def __init__(cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cls._instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SingletonMeta, cls).__call__(*args, **kwargs)
        return cls._instance
