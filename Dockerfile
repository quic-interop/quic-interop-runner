FROM ubuntu:19.04

RUN apt-get update
RUN apt-get install -y python3 python3-pip
RUN pip3 install prettytable termcolor

RUN apt-get install -y docker docker-compose


RUN mkdir /interop
WORKDIR /interop

COPY docker-compose.yml interop.yml run.sh *.py /interop/

ENTRYPOINT [ "./run.sh" ]
