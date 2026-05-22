"""Session manager wrapping ADK's session service with timeout and cleanup."""

from typing import Dict, Optional, Set, Any
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages ADK sessions with timeout monitoring and cleanup."""

    _instance = None
    _initialized = False

    def __new__(cls, session_service=None, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        session_service=None,
        memory_service=None,
        session_timeout_seconds: int = 1200,
        cleanup_interval_seconds: int = 300,
        max_sessions_per_user: Optional[int] = None,
        auto_cleanup: bool = True,
    ):
        if self._initialized:
            return

        if session_service is None:
            from google.adk.sessions import InMemorySessionService

            session_service = InMemorySessionService()

        self._session_service = session_service
        self._memory_service = memory_service
        self._timeout = session_timeout_seconds
        self._cleanup_interval = cleanup_interval_seconds
        self._max_per_user = max_sessions_per_user
        self._auto_cleanup = auto_cleanup

        self._session_keys: Set[str] = set()
        self._user_sessions: Dict[str, Set[str]] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._initialized = True

        logger.info(
            f"Initialized SessionManager - "
            f"timeout: {session_timeout_seconds}s, "
            f"cleanup: {cleanup_interval_seconds}s"
        )

    @classmethod
    def get_instance(cls, **kwargs):
        return cls(**kwargs)

    @classmethod
    def reset_instance(cls):
        if cls._instance and hasattr(cls._instance, "_cleanup_task"):
            task = cls._instance._cleanup_task
            if task:
                try:
                    task.cancel()
                except RuntimeError:
                    pass
        cls._instance = None
        cls._initialized = False

    async def get_or_create_session(
        self,
        session_id: str,
        app_name: str,
        user_id: str,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> Any:
        session_key = f"{app_name}:{session_id}"

        session = await self._session_service.get_session(
            session_id=session_id,
            app_name=app_name,
            user_id=user_id,
        )

        if not session:
            session = await self._session_service.create_session(
                session_id=session_id,
                user_id=user_id,
                app_name=app_name,
                state=initial_state or {},
            )
            logger.info(f"Created new session: {session_key}")
        else:
            logger.debug(f"Retrieved existing session: {session_key}")

        self._track_session(session_key, user_id)

        if self._auto_cleanup and not self._cleanup_task:
            self._start_cleanup_task()

        return session

    async def update_session_state(
        self,
        session_id: str,
        app_name: str,
        user_id: str,
        state_updates: Dict[str, Any],
    ) -> bool:
        try:
            session = await self._session_service.get_session(
                session_id=session_id,
                app_name=app_name,
                user_id=user_id,
            )

            if not (session and state_updates):
                return False

            from google.adk.events import Event, EventActions

            actions = EventActions(state_delta=state_updates)
            event = Event(
                invocation_id=f"state_update_{int(time.time())}",
                author="system",
                actions=actions,
                timestamp=time.time(),
            )
            await self._session_service.append_event(session, event)
            return True
        except Exception as e:
            logger.error(f"Failed to update session state: {e}", exc_info=True)
            return False

    async def get_session_state(
        self,
        session_id: str,
        app_name: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            session = await self._session_service.get_session(
                session_id=session_id,
                app_name=app_name,
                user_id=user_id,
            )
            if not session:
                return None
            if hasattr(session.state, "to_dict"):
                return session.state.to_dict()
            return dict(session.state)
        except Exception as e:
            logger.error(f"Failed to get session state: {e}", exc_info=True)
            return None

    def _track_session(self, session_key: str, user_id: str):
        self._session_keys.add(session_key)
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = set()
        self._user_sessions[user_id].add(session_key)

    def _untrack_session(self, session_key: str, user_id: str):
        self._session_keys.discard(session_key)
        if user_id in self._user_sessions:
            self._user_sessions[user_id].discard(session_key)
            if not self._user_sessions[user_id]:
                del self._user_sessions[user_id]

    def _start_cleanup_task(self):
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._cleanup_loop())
        except RuntimeError:
            logger.debug("No event loop, cleanup will start later")

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}", exc_info=True)

    async def _cleanup_expired_sessions(self):
        current_time = time.time()
        expired_count = 0

        for session_key in list(self._session_keys):
            app_name, session_id = session_key.split(":", 1)
            user_id = None
            for uid, keys in self._user_sessions.items():
                if session_key in keys:
                    user_id = uid
                    break
            if not user_id:
                continue
            try:
                session = await self._session_service.get_session(
                    session_id=session_id,
                    app_name=app_name,
                    user_id=user_id,
                )
                if session and hasattr(session, "last_update_time"):
                    age = current_time - session.last_update_time
                    if age > self._timeout:
                        await self._session_service.delete_session(
                            session_id=session.id,
                            app_name=session.app_name,
                            user_id=session.user_id,
                        )
                        self._untrack_session(session_key, user_id)
                        expired_count += 1
                elif not session:
                    self._untrack_session(session_key, user_id)
            except Exception as e:
                logger.error(f"Error checking session {session_key}: {e}")

        if expired_count > 0:
            logger.info(f"Cleaned up {expired_count} expired sessions")

    async def stop_cleanup_task(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
