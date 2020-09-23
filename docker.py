import logging
import subprocess
import threading
import typing


def execute(cmd: str, log_file: typing.TextIO, log_prefix: str):
    logging.debug("Running: %s", cmd)
    p = subprocess.Popen(
        cmd.split(" "),
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    for line in p.stdout:
        l = log_prefix + ": " + line.rstrip()
        log_file.write(l + '\n')
        logging.debug(l)


class DockerRunner:
    _containers = []

    def __init__(self):
        pass

    def add_container(self, name: str, container: str, env: str):
        self._containers.append({name: name, container: container, env: env})

    def run(self):
        threads = []
        with open("test.log", "w") as f:
            for name, container, env in self._containers:
                def run_container():
                    execute("docker run --rm --env " + env + " " + container, f, name)
                t = threading.Thread(target=run_container)
                t.start()
                threads.append(t)
            # wait for all threads to finish
            for t in threads:
                t.join()
        print("run done")


def main():
    logging.getLogger().setLevel(logging.DEBUG)
    r = DockerRunner()
    r.add_container("client", "traptest", "DURATION=3")
    r.add_container("server", "traptest", "DURATION=20")
    r.run()


if __name__ == "__main__":
    main()
