from rq import Worker

from app.task_queue import queue, redis_conn


def main():
    worker = Worker([queue], connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
