import atexit
import logging
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    Set,
)

from motion.execute import Executor
from motion.route import Route
from motion.utils import DEFAULT_KEY_TTL, configureLogging

logger = logging.getLogger(__name__)


def is_logger_open(logger: logging.Logger) -> bool:
    for handler in logger.handlers:
        if (
            hasattr(handler, "stream")
            and handler.stream is not None
            and not handler.stream.closed
        ):
            return True
    return False


class ComponentInstance:
    def __init__(
        self,
        component_name: str,
        instance_id: str,
        init_state_func: Optional[Callable],
        init_state_params: Optional[Dict[str, Any]],
        save_state_func: Optional[Callable],
        load_state_func: Optional[Callable],
        serve_routes: Dict[str, Route],
        update_routes: Dict[str, List[Route]],
        logging_level: str = "WARNING",
        update_task_type: Literal["thread", "process"] = "thread",
        disable_update_task: bool = False,
        cache_ttl: int = DEFAULT_KEY_TTL,
        redis_socket_timeout: int = 60,
        flush_on_exit: bool = False,
    ):
        """Creates a new instance of a Motion component.

        Args:
            component_name (str):
                Name of the component we are creating an instance of.
            instance_id (str):
                ID of the instance we are creating.
            logging_level (str, optional):
                Logging level for the Motion logger. Uses the logging library.
                Defaults to "WARNING".
        """
        if update_task_type not in ["thread", "process"]:
            raise ValueError("update_task must be either 'thread' or 'process'")

        self._component_name = component_name
        configureLogging(logging_level)
        # self._serverless = serverless
        # indicator = "serverless" if serverless else "local"
        logger.info(f"Creating local instance of {self._component_name}...")
        atexit.register(self.shutdown)

        # Create instance name
        self._instance_name = f"{self._component_name}__{instance_id}"
        self._cache_ttl = cache_ttl

        self.running = False
        self.disable_update_task = disable_update_task
        self.flush_on_exit = flush_on_exit

        if self.disable_update_task and self.flush_on_exit:
            raise ValueError("Cannot flush on exit if update task is disabled.")

        self.flows_run: Set[str] = set()

        self._executor = Executor(
            self._instance_name,
            cache_ttl=self._cache_ttl,
            init_state_func=init_state_func,
            init_state_params=init_state_params if init_state_params else {},
            save_state_func=save_state_func,
            load_state_func=load_state_func,
            serve_routes=serve_routes,
            update_routes=update_routes,
            update_task_type=update_task_type,
            disable_update_task=self.disable_update_task,
            redis_socket_timeout=redis_socket_timeout,
        )
        self.running = True

    def __enter__(self) -> "ComponentInstance":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # type: ignore
        self.shutdown()

    def __del__(self) -> None:
        self.shutdown()

    @property
    def instance_name(self) -> str:
        """Component name with a random phrase to represent
        the name of this instance.
        In the form of componentname__randomphrase.
        """
        return self._instance_name

    @property
    def instance_id(self) -> str:
        """Latter part of the instance name, which is a random phrase
        or a user-defined ID."""
        return self._instance_name.split("__")[-1]

    def close(self, wait_for_logging_threads: bool = False) -> None:
        """Alias for shutdown.

        Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        # Define serve and update operations

        if __name__ == "__main__":
            c_instance = C()
            c_instance.run(...)
            c_instance.run(...)
            c_instance.close()

            # Or, use a context manager
            with C() as c_instance:
                c_instance.run(...)
                c_instance.run(...)
        ```

        Args:
            wait_for_logging_threads (bool, optional): Defaults to False.
        """

        # Call shutdown
        self.shutdown(wait_for_logging_threads=wait_for_logging_threads)

    def shutdown(self, wait_for_logging_threads: bool = False) -> None:
        """Shuts down a Motion component instance, saving state.
        Automatically called when the instance is garbage collected.

        Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        # Define serve and update operations

        if __name__ == "__main__":
            c_instance = C()
            c_instance.run(...)
            c_instance.run(...)
            c_instance.shutdown()

            # Or, use a context manager
            with C() as c_instance:
                c_instance.run(...)
                c_instance.run(...)
        ```
        """
        if self.disable_update_task:
            return

        if not self.running:
            return

        # Flush the update queue
        if self.flush_on_exit:
            for flow_key in self.flows_run:
                self.flush_update(flow_key)

        is_open = is_logger_open(logger)

        if is_open:
            logger.debug(f"Shutting down {self._instance_name}...")

        self._executor.shutdown(
            is_open=is_open, wait_for_logging_threads=wait_for_logging_threads
        )

        self.running = False

    def get_version(self) -> int:
        """
        Gets the state version (might be outdated) currently being
        used for serve ops.

        Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        # Define serve and update operations

        if __name__ == "__main__":
            with C() as c_instance:
                c_instance.get_version() # Returns 1 (first version)
        ```
        """
        return self._executor.version  # type: ignore

    def write_state(self, state_update: Dict[str, Any]) -> None:
        """Writes the state update to the component instance's state.
        If a update op is currently running, the state update will be
        applied after the update op is finished. Warning: this could
        take a while if your update ops take a long time!

        Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        # Define serve and update operations
        ...

        if __name__ == "__main__":
            with C() as c_instance:
                c_instance.read_state("value") # Returns 0
                c_instance.write_state({"value": 1, "value2": 2})
                c_instance.read_state("value") # Returns 1
                c_instance.read_state("value2") # Returns 2
        ```

        Args:
            state_update (Dict[str, Any]): Dictionary of key-value pairs
                to update the state with.
            latest (bool, optional): Whether or not to apply the update
                to the latest version of the state.
                If true, Motion will redownload the latest version
                of the state and apply the update to that version. You
                only need to set this to true if you are updating an
                instance you connected to a while ago and might be
                outdated. Defaults to False.
        """
        self._executor._updateState(state_update)

    def read_state(self, key: str, default_value: Optional[Any] = None) -> Any:
        """Gets the current value for the key in the component instance's state.

        Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        # Define serve and update operations
        ...

        if __name__ == "__main__":
            with C() as c_instance:
                c_instance.read_state("value") # Returns 0
                c_instance.run(...)
                c_instance.read_state("value") # This will return the current
                # value of "value" in the state
        ```

        Args:
            key (str): Key in the state to get the value for.
            default_value (Optional[Any], optional): Default value to return
                if the key is not found. Defaults to None.

        Returns:
            Any: Current value for the key, or default_value if the key
            is not found.
        """
        self._executor._loadState()
        return self._executor._state.get(key, default_value)

    def flush_update(self, flow_key: str) -> None:
        """Flushes the update queue corresponding to the flow
        key, if it exists, and updates the instance state.
        Warning: this is a blocking operation and could take
        a while if your update op takes a long time!

        Example Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        @C.serve("add")
        def add(state, value):
            return state["value"] + value

        @C.update("add")
        def add(state, value):
            return {"value": state["value"] + value}

        @C.serve("multiply")
        def multiply(state, value):
            return state["value"] * value

        if __name__ == "__main__":
            with C() as c: # Create instance of C
                c.run("add", props={"value": 1})
                c.flush_update("add") # (1)!
                c.run("add", props={"value": 2}) # This will use the updated state

        # 1. Waits for the update op to finish, then updates the state
        ```

        Args:
            flow_key (str): Key of the flow.

        Raises:
            RuntimeError:
                If the component instance was initialized as disable_update_task.
        """
        if self.disable_update_task:
            raise RuntimeError("Cannot run a disable_update_task component instance.")

        self._executor.flush_update(flow_key)

    def gen(
        self,
        flow_key: str,
        props: Dict[str, Any] = {},
        ignore_cache: bool = False,
        force_refresh: bool = False,
        flush_update: bool = False,
    ) -> Generator[Any, None, None]:
        """Runs the flow (serve and update ops) for the specified key and
        yields the results as they come in, as a generator. Use this if your
        serve op is a generator function. If your serve op just returns a
        value, use run instead. You should use agen as opposed to gen if your
        serve op is an async generator function.

        Example Usage:
        ```python
        from motion import Component
        import asyncio

        C = Component("MyComponent")

        @C.serve("count")
        def count(state, value):
            for i in range(value):
                yield i

        def main():
            with C() as c:
                for elem in c.gen("count", props={"value": 3}): # (1)!
                    print(elem) # Prints 0, 1, 2

        if __name__ == "__main__":
            asyncio.run(main())

        # 1. Iterates over the generator returned by the "count" serve op
        ```

        Args:
            flow_key (str): Key of the flow to run.
            props (Dict[str, Any]): Keyword arguments to pass into the
                flow ops, in addition to the state.
            ignore_cache (bool, optional):
                If True, ignores the cache and runs the serve op. Does not
                force refresh the state. Defaults to False.
            force_refresh (bool, optional): Whether to wait for all the pending
                updates to finish processing, resulting in the most up-to-date
                state, before running the serve op. Defaults to False, where a
                stale version of the state or a cached result may be used.
            flush_update (bool, optional):
                If True, waits for the update op to finish executing before
                returning. If the update queue hasn't reached batch_size
                yet, the update op runs anyways. Force refreshes the
                state after the update op completes. Defaults to False.

        Raises:
            ValueError: If more than one flow key-value pair is passed.
                If flush_update is called and the component instance update
                processes are disabled.

        Returns:
            Awaitable[Any]: Awaitable Result of the serve call.
        """
        for elem in self._executor.run(
            key=flow_key,
            props=props,
            ignore_cache=ignore_cache,
            force_refresh=force_refresh,
            flush_update=flush_update,
        ):  # type: ignore
            yield elem

        self.flows_run.add(flow_key)

    def run(
        self,
        # *,
        flow_key: str,
        props: Dict[str, Any] = {},
        ignore_cache: bool = False,
        force_refresh: bool = False,
        flush_update: bool = False,
    ) -> Any:
        """Runs the flow (serve and update ops) for the keyword argument
        passed in. If the key is not found to have any ops, an error
        is raised. Only one flow key should be passed in.

        Example Usage:
        ```python
        from motion import Component

        C = Component("MyComponent")

        @C.init_state
        def setUp():
            return {"value": 0}

        @C.serve("add")
        def add(state, value):
            return state["value"] + value

        @C.update("add")
        def add(state, value):
            return {"value": state["value"] + value}

        if __name__ == "__main__":
            with C() as c: # Create instance of C
                c.run("add", props={"value": 1}, flush_update=True) # (1)!
                c.run("add", props={"value": 1}) # Returns 1
                c.run("add", props={"value": 2}) # (2)!

                c.run("add", props={"value": 3})

                c.run("add", props={"value": 3}, force_refresh=True) # (3)!

        # 1. Waits for the update op to finish, then updates the state
        # 2. Returns 2, result state["value"] = 4
        # 3. Force refreshes the state before running the flow by waiting
        #    for all pending updates to finish processing. This
        #    reruns the serve op even though the result might be cached.
        ```


        Args:
            flow_key (str): Key of the flow to run.
            props (Dict[str, Any]): Keyword arguments to pass into the
                flow ops, in addition to the state.
            ignore_cache (bool, optional):
                If True, ignores the cache and runs the serve op. Does not
                force refresh the state. Defaults to False.
            force_refresh (bool, optional): Whether to wait for all the pending
                updates to finish processing, resulting in the most up-to-date
                state, before running the serve op. Defaults to False, where a
                stale version of the state or a cached result may be used.
            flush_update (bool, optional):
                If True, waits for the update op to finish executing before
                returning. If the update queue hasn't reached batch_size
                yet, the update op runs anyways. Force refreshes the
                state after the update op completes. Defaults to False.

         Raises:
            ValueError: If more than one flow key-value pair is passed.
            RuntimeError:
                If flush_update is called and the component instance update
                processes are disabled.

        Returns:
            Any: Result of the serve call. Might take a long time
            to run if `flush_update = True` and the update operation is
            computationally expensive.
        """

        serve_result = []
        for elem in self.gen(
            flow_key, props, ignore_cache, force_refresh, flush_update
        ):
            serve_result.append(elem)

        return serve_result[0]

    async def agen(
        self,
        flow_key: str,
        props: Dict[str, Any] = {},
        ignore_cache: bool = False,
        force_refresh: bool = False,
        flush_update: bool = False,
    ) -> AsyncGenerator[Any, None]:
        """Async version of gen. Runs the flow (serve and update ops) for
        the specified key and yields the results as they come in,
        as a generator. Use this if your serve op is an async
        generator function. You should use agen as opposed to gen if your
        serve op is an async function.

        Example Usage:
        ```python
        from motion import Component
        import asyncio

        C = Component("MyComponent")

        @C.serve("count")
        async def count(state, value):
            for i in range(value):
                yield i
                await asyncio.sleep(i)

        async def main():
            with C() as c:
                async for elem in c.agen("count", props={"value": 3}):
                    print(elem) # Prints 0, 1, 2

        if __name__ == "__main__":
            asyncio.run(main())
        ```

        Args:
            flow_key (str): Key of the flow to run.
            props (Dict[str, Any]): Keyword arguments to pass into the
                flow ops, in addition to the state.
            ignore_cache (bool, optional):
                If True, ignores the cache and runs the serve op. Does not
                force refresh the state. Defaults to False.
            force_refresh (bool, optional): Whether to wait for all the pending
                updates to finish processing, resulting in the most up-to-date
                state, before running the serve op. Defaults to False, where a
                stale version of the state or a cached result may be used.
            flush_update (bool, optional):
                If True, waits for the update op to finish executing before
                returning. If the update queue hasn't reached batch_size
                yet, the update op runs anyways. Force refreshes the
                state after the update op completes. Defaults to False.

        Raises:
            ValueError: If more than one flow key-value pair is passed.
                If flush_update is called and the component instance update
                processes are disabled.

        Returns:
            Awaitable[Any]: Awaitable Result of the serve call.
        """
        async for elem in self._executor.arun(
            key=flow_key,
            props=props,
            ignore_cache=ignore_cache,
            force_refresh=force_refresh,
            flush_update=flush_update,
        ):  # type: ignore
            yield elem

        self.flows_run.add(flow_key)

    async def arun(
        self,
        # *,
        flow_key: str,
        props: Dict[str, Any] = {},
        ignore_cache: bool = False,
        force_refresh: bool = False,
        flush_update: bool = False,
    ) -> Awaitable[Any]:
        """Async version of run. Runs the flow (serve and update ops) for
        the specified key. You should use arun if either the serve or update op
        is an async function.

        Example Usage:
        ```python
        from motion import Component
        import asyncio

        C = Component("MyComponent")

        @C.serve("sleep")
        async def sleep(state, value):
            await asyncio.sleep(value)
            return "Slept!"

        async def main():
            with C() as c:
                await c.arun("sleep", props={"value": 1})

        if __name__ == "__main__":
            asyncio.run(main())
        ```

        Args:
            flow_key (str): Key of the flow to run.
            props (Dict[str, Any]): Keyword arguments to pass into the
                flow ops, in addition to the state.
            ignore_cache (bool, optional):
                If True, ignores the cache and runs the serve op. Does not
                force refresh the state. Defaults to False.
            force_refresh (bool, optional): Whether to wait for all the pending
                updates to finish processing, resulting in the most up-to-date
                state, before running the serve op. Defaults to False, where a
                stale version of the state or a cached result may be used.
            flush_update (bool, optional):
                If True, waits for the update op to finish executing before
                returning. If the update queue hasn't reached batch_size
                yet, the update op runs anyways. Force refreshes the
                state after the update op completes. Defaults to False.

        Raises:
            ValueError: If more than one flow key-value pair is passed.
                If flush_update is called and the component instance update
                processes are disabled.

        Returns:
            Awaitable[Any]: Awaitable Result of the serve call.
        """

        # Run agen and collect the results into a list
        results = []

        async for elem in self.agen(
            flow_key, props, ignore_cache, force_refresh, flush_update
        ):
            results.append(elem)

        return results[0]  # type: ignore
