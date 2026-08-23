import os
import socket

from scripts.process_cleanup_check import check_process_cleanup, is_port_open, process_exists


def test_process_exists_for_current_process():
    assert process_exists(os.getpid()) is True


def test_is_port_open_reports_bound_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert is_port_open("127.0.0.1", port) is True


def test_cleanup_passes_for_absent_process_and_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]

    result = check_process_cleanup(pid=999999, host="127.0.0.1", port=port, timeout_seconds=0.2)

    assert result["status"] == "PASS"
    assert result["pid"] == 999999
    assert result["port"] == port
