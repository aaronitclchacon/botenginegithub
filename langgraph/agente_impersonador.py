# agente_langgraph.py
import os
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from typing import List, TypedDict, Dict, Any

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# No es necesario obtener la key aquí si se pasa en la inicialización o ya está en el entorno
# openai_key = os.getenv("OPENAI_API_KEY")

class AgentState(TypedDict):
    input: str
    chat_history: List[BaseMessage]
    output: str

def create_langgraph_agent():
    logger.info("DEBUG: create_langgraph_agent() en Python ha sido llamado.")

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.error("Error: La variable de entorno OPENAI_API_KEY no está definida.")
        # Podríamos devolver un grafo "falso" para evitar que la app crashee,
        # pero por ahora lo dejamos fallar para que sea evidente.
        raise ValueError("OPENAI_API_KEY no encontrada en el entorno.")

    llm = ChatOpenAI(model="gpt-4o", api_key=openai_key, temperature=0.7)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "Eres una persona real, te llamas BotEngine, eres amable y cercana. Escribe con naturalidad y usa emojis cuando tenga sentido."),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
    ])

    llm_chain = prompt | llm

    async def run_agent_node(state: AgentState) -> Dict[str, Any]:
        # Construir la entrada para el LLM, asegurando que chat_history siempre exista
        agent_input = {
            "input": state["input"],
            "chat_history": state.get("chat_history", [])  # Usar .get() con una lista vacía como valor por defecto
        }
        logger.info(f"INPUT a la cadena LLM: {agent_input}")
        response_message = await llm_chain.ainvoke(agent_input)
        logger.info(f"SALIDA de la cadena LLM (BaseMessage): {response_message}")
        return {"output": response_message.content}

    def update_chat_history_node(state: AgentState) -> Dict[str, List[BaseMessage]]:
        # Obtener el historial existente o una lista vacía si es el primer turno
        chat_history = state.get("chat_history", [])
        
        # Añadir el último intercambio (humano y IA) al historial
        chat_history.append(HumanMessage(content=state["input"]))
        chat_history.append(AIMessage(content=state["output"]))

        # Devolver el historial actualizado para que se guarde en el estado
        return {"chat_history": chat_history}

    workflow = StateGraph(AgentState)

    workflow.add_node("agent", run_agent_node)
    workflow.add_node("update_history", update_chat_history_node)

    workflow.set_entry_point("agent")

    workflow.add_edge("agent", "update_history")
    workflow.add_edge("update_history", END)

    # El checkpointer es necesario para mantener la memoria entre invocaciones
    checkpointer = MemorySaver()
    compiled_graph = workflow.compile(checkpointer=checkpointer)
    
    # Devolvemos el grafo y el checkpointer como una tupla
    return compiled_graph, checkpointer