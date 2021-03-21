try:
    from xmlrpc.client import ServerProxy

    from supervisor.xmlrpc import SupervisorTransport
except ImportError:
    no_lib = True
else:
    no_lib = False


def supervisor_restart(
    service: str = "web-api",
    # default supervisor configuration
    socketpath: str = "unix:///var/run/supervisor.sock"
) -> bool:
    """Restart service by xml-rpc of supervisor.
    """
    if no_lib:
        return False

    server = ServerProxy(
        "http://127.0.0.1",
        transport=SupervisorTransport(None, None, socketpath)
    )
    result = True
    try:
        if service:
            server.supervisor.stopProcess(service)
            server.supervisor.startProcess(service)
        else:
            server.supervisor.restart()
    except Exception as err:
        result = False

    return True
