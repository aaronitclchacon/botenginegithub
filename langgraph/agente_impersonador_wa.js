// agente_langgraph.js
const { ChatOpenAI } = require('@langchain/openai');
const { ChatPromptTemplate, MessagesPlaceholder } = require('@langchain/core/prompts');
const { HumanMessage, AIMessage, SystemMessage } = require('@langchain/core/messages');
const { StateGraph, END } = require('@langchain/langgraph');
const { MemorySaver } = require('@langchain/langgraph');

// Definir el esquema del estado para LangGraph
const agentStateSchema = {
    input: {
        value: (x, y) => y,
        default: () => ""
    },
    chat_history: {
        value: (x, y) => y,
        default: () => []
    },
    output: {
        value: (x, y) => y,
        default: () => ""
    }
};

function createLangGraphAgent() {
    console.log('DEBUG: createLangGraphAgent() ha sido llamado.');

    const openaiKey = process.env.OPENAI_API_KEY;
    const llm = new ChatOpenAI({
        model: "gpt-4o",
        apiKey: openaiKey,
        temperature: 0.7
    });

    const prompt = ChatPromptTemplate.fromMessages([
        ["system", "Eres una persona real, te llamas BotEngine, eres amable y cercana. Escribe con naturalidad y usa emojis cuando tenga sentido."],
        new MessagesPlaceholder("chat_history"),
        ["human", "{input}"]
    ]);

    const chain = prompt.pipe(llm);

    // Nodo del agente
    async function agentNode(state) {
        const agentInput = {
            input: state.input,
            chat_history: state.chat_history || []
        };

        console.log('INPUT a chain:', JSON.stringify(agentInput, null, 2));

        const response = await chain.invoke(agentInput);
        
        console.log('SALIDA DE chain (BaseMessage):', response);

        return {
            output: response.content
        };
    }

    // Nodo para actualizar el historial
    function updateHistoryNode(state) {
        const chatHistory = state.chat_history || [];
        const userInput = state.input;
        const agentResponseContent = state.output;

        chatHistory.push(new HumanMessage(userInput));
        chatHistory.push(new AIMessage(agentResponseContent));

        return { chat_history: chatHistory };
    }

    // Crear el grafo de estados
    const workflow = new StateGraph({
        channels: agentStateSchema
    });

    // Agregar nodos
    workflow.addNode("agent", agentNode);
    workflow.addNode("update_history", updateHistoryNode);

    // Definir el punto de entrada
    workflow.setEntryPoint("agent");

    // Agregar aristas
    workflow.addEdge("agent", "update_history");
    workflow.addEdge("update_history", END);

    // Compilar el grafo con checkpointer
    const checkpointer = new MemorySaver();
    const compiledGraph = workflow.compile({ checkpointer });

    return { compiledGraph, checkpointer };
}

module.exports = { createLangGraphAgent }; 