import logging
import shutil
import subprocess
import threading


class DockerRunner:
    _containers = None
    _cond = None
    _timeout = 0  # in seconds
    _expired = False

    def __init__(self, timeout: int):
        self._containers = []
        self._cond = threading.Condition()
        self._timeout = timeout

    def add_container(self, name: str, env: dict):
        self._containers.append({"name": name, "env": env})

    def _run_container(self, cmd: str, env: dict, name: str):
        self._execute(cmd, env, name)
        with self._cond:
            logging.debug("%s container returned.", name)
            self._cond.notify()

    def _execute(self, cmd: str, env: dict = {}, name: str = ""):
        p = subprocess.Popen(
            cmd.split(" "),
            bufsize=1,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        for line in p.stdout:
            l = ""
            if name:
                l = name + ": "
            l = l + line.rstrip()
            logging.debug(l)

    def _run_timer(self):
        logging.debug("Timer expired. Stopping all containers.")
        self._expired = True
        with self._cond:
            self._cond.notify()

    def run(self) -> bool:  # returns if the timer expired
        threads = []
        # Start all containers (in separate threads)
        docker_compose = shutil.which("docker-compose")
        for e in self._containers:
            t = threading.Thread(
                target=self._run_container,
                kwargs={
                    "cmd": docker_compose + " up " + e["name"],
                    "env": e["env"],
                    "name": e["name"],
                },
            )
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
            self._execute(
                shutil.which("docker-compose") + " stop -t 5 " + " ".join(names)
            )
        # wait for all threads to finish
        for t in threads:
            t.join()
        timer.cancel()
        return self._expired
