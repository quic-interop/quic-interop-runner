import logging
import subprocess
import threading
import typing


class DockerRunner:
    _containers = []
    _cond = None
    _timeout = 0  # in seconds

    def __init__(self, timeout: int):
        self._cond = threading.Condition()
        self._timeout = timeout

    def add_container(self, name: str, container: str, env: str):
        self._containers.append({"name": name, "container": container, "env": env})

    def _execute(self, cmd: str, log_file: typing.TextIO, name: str):
        logging.debug("Running: %s", cmd)
        p = subprocess.Popen(
            cmd.split(" "),
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        for line in p.stdout:
            l = name + ": " + line.rstrip()
            log_file.write(l + "\n")
            logging.debug(l)
        with self._cond:
            logging.debug("%s container returned.", name)
            self._cond.notify()

    def _run_timer(self):
        logging.info("Timer expired. Stopping all containers.")
        with self._cond:
            self._cond.notify()

    def run(self):
        threads = []
        with open("test.log", "w") as f:
            # Start all containers (in separate threads)
            for e in self._containers:

                def run_container():
                    self._execute(
                        "docker run --rm --name {} --env {} {}".format(
                            e["name"], e["env"], e["container"]
                        ),
                        f,
                        e["name"],
                    )

                t = threading.Thread(target=run_container)
                t.start()
                threads.append(t)
            # set a timer
            timer = threading.Timer(self._timeout, self._run_timer)
            timer.start()

            # Wait for the first container to exit.
            # Then stop all other docker containers.
            with self._cond:
                self._cond.wait()
                names = [x["name"] for x in self._containers]
                subprocess.run(
                    "docker stop " + " ".join(names),
                    shell="True",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            # wait for all threads to finish
            for t in threads:
                t.join()
            timer.cancel()


def main():
    logging.getLogger().setLevel(logging.DEBUG)
    r = DockerRunner(10)
    r.add_container("client", "traptest", "DURATION=3")
    r.add_container("server", "traptest", "DURATION=2000")
    r.run()


if __name__ == "__main__":
    main()
