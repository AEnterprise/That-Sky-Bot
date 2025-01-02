import asyncio
import random
import time
from asyncio import CancelledError, shield
from pprint import pprint

from utils.Logging import log_format, TCol

total_sleep_time = 0
total_tasks_started = 0
total_tasks_finished = 0


async def sleep_maker(queue):
    global total_sleep_time
    i = 1
    while True:
        my_time = random.uniform(0.05, 3.0)
        sleep_for = {"time": my_time, "sequence": i}
        i += 1
        total_sleep_time += sleep_for['time']
        queue.put_nowait(sleep_for)
        print(log_format(f"{sleep_for['sequence']}. +{sleep_for['time']:.2f}", TCol.Green))
        await asyncio.sleep(0.5)


async def worker(name, queue, job):
    print(f"\t--start task {name}")
    while True:
        # Get a work_item out of the queue
        work_item = await queue.get()
        try:
            await job(work_item)
        except CancelledError:
            print(f"work item has been canceled")
        queue.task_done()


async def do_job(work_item):
    global total_tasks_started
    global total_tasks_finished
    try:
        # process the work_item
        print(f"\t\tstart job {work_item['sequence']}")
        total_tasks_started += 1
        # shield tasks so a CancelledError doesn't stop a running task
        await shield(asyncio.sleep(work_item['time']))
        print("not canceled")
    finally:
        # Notify the queue that the work_item has been processed
        print(f"\t\tjob {work_item['sequence']} took {work_item['time']:.2f} seconds")
        total_tasks_finished += 1


async def main():
    global total_sleep_time
    global total_tasks_started
    global total_tasks_finished

    queue = asyncio.Queue()
    tasks = []
    started_at = time.monotonic()
    try:
        work_task = asyncio.create_task(worker(f'worker', queue, do_job))
        tasks.append(work_task)

        another_task = asyncio.create_task(sleep_maker(queue))
        tasks.append(another_task)

        print("started...")
        await asyncio.sleep(200)
        print("end.")
    except CancelledError:
        print(log_format(f"==================================================", TCol.Warning))
    except BaseException as e:
        pprint(e)
        pass
    finally:
        # Wait until all worker tasks are canceled.
        print(f"there are {queue.qsize()} items left...")
        await queue.join()
        for task in tasks:
            task.cancel()

    total_slept_for = time.monotonic() - started_at

    print(log_format(f'==================================================', TCol.Fail))
    print(f'{TCol.Header.value}worker slept for {total_slept_for:.2f} seconds')
    print(f'total expected sleep time: {total_sleep_time:.2f} seconds{TCol.End.value}')
    print(f'tasks started: {total_tasks_started} finished: {total_tasks_finished}')

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("exiting...")
