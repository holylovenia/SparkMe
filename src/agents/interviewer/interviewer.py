import asyncio
import os
import random
import re
from typing import TYPE_CHECKING, TypedDict, Tuple

import json

from src.agents.base_agent import BaseAgent
from src.agents.interviewer.prompts import get_prompt
from src.agents.interviewer.tools import EndConversation, RespondToUser
from src.agents.shared.memory_tools import Recall
from src.utils.llm.engines import get_engine
from src.utils.llm.prompt_utils import format_prompt
from src.interview_session.session_models import Participant, Message, MessageType
from src.utils.llm.xml_formatter import parse_rubric_call
from src.utils.logger.session_logger import SessionLogger
from src.utils.constants.colors import GREEN, RESET
from src.content.question_bank.question import Rubric

if TYPE_CHECKING:
    from src.interview_session.interview_session import InterviewSession



class TTSConfig(TypedDict, total=False):
    """Configuration for text-to-speech."""
    enabled: bool
    provider: str  # e.g. 'openai'
    voice: str     # e.g. 'alloy'


class InterviewerConfig(TypedDict, total=False):
    """Configuration for the Interviewer agent."""
    user_id: str
    tts: TTSConfig
    interview_description: str


class Interviewer(BaseAgent, Participant):
    '''Inherits from BaseAgent and Participant. Participant is a class that all agents in the interview session inherit from.'''

    def __init__(self, config: InterviewerConfig, interview_session: 'InterviewSession'):
        BaseAgent.__init__(
            self, name="Interviewer",
            description="The agent that holds the interview and asks questions.",
            config=config)
        Participant.__init__(
            self, title="Interviewer",
            interview_session=interview_session)

        self.engines = [
            get_engine(
                model_name=config.get("model_name_1", os.getenv("MODEL_NAME_1", "lipsum:model-1")), base_url=config.get("base_url", None)
            ),
            get_engine(
                model_name=config.get("model_name_2", os.getenv("MODEL_NAME_2", "lipsum:model-2")), base_url=config.get("base_url", None)
            ),
            get_engine(
                model_name=config.get("model_name_3", os.getenv("MODEL_NAME_3", "lipsum:model-3")), base_url=config.get("base_url", None)
            ),
            get_engine(
                model_name=config.get("model_name_4", os.getenv("MODEL_NAME_4", "lipsum:model-4")), base_url=config.get("base_url", None)
            ),
        ]

        self.interview_description = config.get("interview_description")
        self.tools = {
            "recall": Recall(memory_bank=self.interview_session.memory_bank),
            "respond_to_user": RespondToUser(
                tts_config=config.get("tts", {}),
                base_path= \
                    f"{os.getenv('DATA_DIR', 'data')}/{config.get('user_id')}/",
                on_response=self._handle_response,
                on_turn_complete=lambda: setattr(
                    self, '_turn_to_respond', False)
            ),
            # "end_conversation": EndConversation(
            #     on_goodbye=lambda goodbye: (
            #         self.add_event(sender=self.name,
            #                        tag="goodbye", content=goodbye),
            #         self.interview_session.add_message_to_chat_history(
            #             role=self.title, content=goodbye)
            #     ),
            #     on_end=lambda: (
            #         setattr(self, '_turn_to_respond', False),
            #         self.interview_session.end_session()
            #     )
            # )
        }

        self._turn_to_respond = False
        self._max_consideration_iterations = 4

    def _handle_quantify_response(self, quantified_response: str,
                                  original_response: str) -> Tuple[str, Rubric]:
        # 2. Parse the <tool_calls> block from the response
        final_question_text = original_response
        final_rubric = None
        try:
            parsed_calls = parse_rubric_call(quantified_response)
            for parsed_call in parsed_calls:
                is_quantifiable = str(parsed_call.get('quantifiable', 'false')).lower() == 'true'

                if is_quantifiable:
                    final_question_text = parsed_call.get('question', original_response)
                    rubric_data_str = parsed_call.get('rubric')
                    if rubric_data_str and isinstance(rubric_data_str, str):
                        # The rubric might be a string representation of JSON
                        try:
                            rubric_data = json.loads(rubric_data_str)
                            final_rubric = Rubric(**rubric_data) # Need to be in string
                        except json.JSONDecodeError:
                            SessionLogger.log_to_file(
                                "execution_log",
                                f"Could not parse rubric JSON string: {rubric_data_str}",
                                log_level="warning"
                            )
                    elif isinstance(rubric_data_str, dict): # Sometimes it's already a dict
                        final_rubric = Rubric(**rubric_data_str) # Need to be in string

        except Exception as e:
            # If parsing fails for any reason, log it but fall back gracefully
            SessionLogger.log_to_file(
                "execution_log",
                f"Could not parse rubric response: {e}. Using original question.",
                log_level="warning"
            )
            final_question_text = original_response
            final_rubric = None

        return final_question_text, final_rubric

    async def _handle_response(self, response: str, subtopic_id: str = "") -> str:
        """Handle responses from the RespondToUser tool by quantifying it and adding them to chat history.
        
        Args:
            response: The response text to add to chat history
            topic_id: The topic ID of the response
            subtopic_id: The subtopic ID of the response
        """
        # # Quantify question even further
        # quantify_prompt = format_prompt(get_prompt("quantify_question"), {"question_text": response})
        # self.add_event(sender=self.name, tag="llm_prompt", content=quantify_prompt)
        # quantified_response = await self.call_engine_async(quantify_prompt)
        # print(f"{GREEN}Interviewer Quantified:\n{quantified_response}{RESET}")
        # quantified_question, rubric = self._handle_quantify_response(quantified_response=quantified_response,
        #                                                              original_response=response)
        
        # If we disable quantification
        quantified_question = response
        rubric = None
        
        self.interview_session.add_message_to_chat_history(
            role=self.title,
            content=quantified_question,
            metadata={'subtopic_id': str(subtopic_id), "rubric": rubric},
        )
        self.add_event(sender=self.name, tag="message",
                       content=quantified_question)
        
        return quantified_question

    async def on_message(self, message: Message):
        if message:
            SessionLogger.log_to_file(
                "execution_log",
                f"[NOTIFY] Interviewer received message from {message.role}"
            )
            self.add_event(sender=message.role, tag="message", content=message.content)

        self._turn_to_respond = True
        prompt = self._get_prompt()
        self.add_event(sender=self.name, tag="llm_prompt", content=prompt)

        ENGINE_TIMEOUT = float(os.getenv("ENGINE_TIMEOUT_SECONDS", "60"))

        async def _call_with_timeout(engine, prompt):
            return await asyncio.wait_for(
                self.call_engine_async(engine, prompt),
                timeout=ENGINE_TIMEOUT
            )

        tasks   = [_call_with_timeout(engine, prompt) for engine in self.engines]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        _responses   = []
        _model_names = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                SessionLogger.log_to_file(
                    "execution_log",
                    f"[INTERVIEWER] Engine {i+1} ({self.engines[i].model_name}) failed: {result}",
                    log_level="error"
                )
            else:
                print(f"{GREEN}Interviewer (model {i+1} — {self.engines[i].model_name}):\n{result}{RESET}")
                _responses.append(result)
                _model_names.append(self.engines[i].model_name)

        if not _responses:
            SessionLogger.log_to_file(
                "execution_log",
                "[INTERVIEWER] All engines failed or timed out.",
                log_level="error"
            )
            self._turn_to_respond = False
            return

        temp = list(zip(_model_names, _responses))
        random.shuffle(temp)
        model_names, responses = zip(*temp)

        try:
            self.interview_session.present_as_options(
                role=self.title,
                content=responses,
                message_type=MessageType.CONVERSATION,
                model_names=model_names,
            )
            for response in responses:
                self.add_event(sender=self.name, tag="message", content=response)
        except Exception as e:
            print(f"Error presenting as options: {e}. Falling back.")
            await self._handle_response(responses[0])

        self._turn_to_respond = False

    def _get_prompt(self):
    # Gets the prompt for the interviewer — chat history only.

        topic   = getattr(self.interview_session, 'topic',   'the chosen topic')
        country = getattr(self.interview_session, 'country', 'the chosen country')

        # Collect all user and interviewer messages in order
        chat_history_events = self.get_event_stream_str(
            [
                {"sender": "Interviewer", "tag": "message"},
                {"sender": "User",        "tag": "message"},
            ],
            as_list=True
        )

        recent_events = (
            chat_history_events[-self._max_events_len:]
            if len(chat_history_events) > self._max_events_len
            else chat_history_events
        )

        chat_history_str = '\n'.join(recent_events) if recent_events else "No messages yet."

        is_first_turn = not any(
            e.startswith('<Interviewer>') for e in chat_history_events
        )

        instruction = (
            f"You are conducting an interview about \"{topic}\" "
            f"with a participant that is interested about {country}. "
            f"Based on the conversation so far, give a natural response "
            f"that might deepens their understanding of \"{topic}\" in {country}."
        )

        return (
            f"{instruction}\n\n"
            f"<conversation_history>\n{chat_history_str}\n</conversation_history>\n\n"
            f"Respond with only your next interview message, "
            f"without any preamble or tags."
        )

    # def _format_strategic_questions(self) -> str:
    #     """
    #     Format strategic question suggestions from StrategicPlanner.

    #     Returns formatted string with strategic questions or empty state message.
    #     Handles case where suggestions may be stale (from 3-5 turns ago).
    #     """
    #     # Access strategic state from StrategicPlanner
    #     strategic_state = self.interview_session.strategic_planner.strategic_state
    #     suggestions = strategic_state.strategic_question_suggestions

    #     if not suggestions:
    #         return "No strategic question suggestions available yet. Use coverage-based heuristics to select questions from the topics list."

    #     # Get top rollout if available
    #     top_rollout = None
    #     if strategic_state.rollout_predictions:
    #         top_rollout = strategic_state.rollout_predictions[0]

    #     formatted_lines = []

    #     # Add top rollout context if available
    #     if top_rollout:
    #         formatted_lines.append("**Highest-Utility Conversation Path Predicted:**")
    #         formatted_lines.append(f"Utility Score: {top_rollout.utility_score:.3f} (Higher is better)")
    #         formatted_lines.append(f"- Expected new subtopics covered: {top_rollout.expected_coverage_delta}")
    #         formatted_lines.append(f"- Emergence potential: {top_rollout.emergence_potential:.2f}")
    #         formatted_lines.append(f"- Cost (turns): {top_rollout.cost_estimate}")
    #         formatted_lines.append("")
    #         formatted_lines.append("The questions below are optimized to align with this high-utility path.")
    #         formatted_lines.append("")

    #     # Format suggestions by priority (high to low)
    #     sorted_suggestions = sorted(suggestions, key=lambda x: x.get('priority', 0), reverse=True)

    #     formatted_lines.append("**Strategic Question Suggestions (sorted by priority):**")
    #     formatted_lines.append("")
    #     for i, suggestion in enumerate(sorted_suggestions, 1):
    #         formatted_lines.append(f"{i}. **{suggestion['content']}**")
    #         formatted_lines.append(f"   - Target: Subtopic {suggestion['subtopic_id']}")
    #         formatted_lines.append(f"   - Strategy: {suggestion['strategy_type']}")
    #         formatted_lines.append(f"   - Priority: {suggestion['priority']}/10")
    #         formatted_lines.append(f"   - Reasoning: {suggestion['reasoning']}")
    #         formatted_lines.append("")  # Blank line between suggestions

    #     return "\n".join(formatted_lines)

    # def _should_include_strategic_questions(self) -> bool:
    #     """
    #     Determine if strategic questions should be included in the prompt.

    #     Strategic questions become stale after exceeding the rollout horizon.
    #     Only include them if they are fresh (within horizon + buffer).

    #     Returns:
    #         bool: True if strategic questions should be included, False if stale
    #     """
    #     strategic_state = self.interview_session.strategic_planner.strategic_state

    #     # If no suggestions exist, don't include
    #     if not strategic_state.strategic_question_suggestions:
    #         return False

    #     # Calculate current turn (count User messages)
    #     current_turn = len([
    #         m for m in self.interview_session.chat_history
    #         if m.role == "User"
    #     ])

    #     # Get last planning turn from strategic state
    #     last_planning_turn = strategic_state.last_planning_turn

    #     # If planning hasn't run yet (turn 0), don't include
    #     if last_planning_turn == 0:
    #         return False

    #     # Get rollout horizon from strategic planner
    #     rollout_horizon = self.interview_session.strategic_planner.rollout_horizon

    #     # Calculate staleness: questions are stale if we're beyond horizon + buffer
    #     # Buffer of 2 turns accounts for: 1) planning completes after trigger, 2) grace period
    #     staleness_threshold = last_planning_turn + rollout_horizon + 2

    #     # Include questions only if NOT stale
    #     is_fresh = current_turn <= staleness_threshold

    #     if not is_fresh:
    #         SessionLogger.log_to_file(
    #             "execution_log",
    #             f"[NOTIFY] (Interviewer) Strategic questions are stale "
    #             f"(last_planning_turn={last_planning_turn}, current_turn={current_turn}, "
    #             f"threshold={staleness_threshold}). Excluding from prompt."
    #         )

    #     return is_fresh
