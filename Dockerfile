FROM python:3.8-slim

RUN apt-get update
RUN apt-get install -y iputils-ping telnet vim

# 设置时区
# https://stackoverflow.com/questions/40234847/docker-timezone-in-ubuntu-16-04-image
RUN ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && dpkg-reconfigure -f noninteractive tzdata

WORKDIR /crypto_robot
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .

# 例子: docker build ... --build-arg numprocs=2
# 启动多少个进程. 默认: 1
# ARG numprocs=6

# 删除环境变量文件
# RUN rm -f .env

# 修改 supervisord 配置文件
RUN cp supervisord.template.conf supervisord.conf
RUN echo "\n\
[program:crypto_robot] \n\
directory=/crypto_robot \n\
command=python -m crypto_robot.main \n\
;numprocs=${numprocs} \n\
;process_name=%(process_num)02d \n\
stdout_logfile=/crypto_robot \n\
stderr_logfile=/crypto_robot \n\
" >> supervisord.conf

# CMD python -m crypto_robot.main
CMD supervisord --nodaemon -c supervisord.conf
