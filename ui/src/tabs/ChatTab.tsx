import { useState, useRef, useEffect } from 'react';
import { Send, Trash2, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useAppStore } from '../store/useAppStore';

// Persona-specific loading phrases (match telegram-processor); show one at random when waiting.
const LOADING_PHRASES: Record<string, string[]> = {
  roleplay: [
    "Mm, give me a moment...",
    "Thinking... (don't go anywhere)",
    "One second, love...",
    "Let me sit with that...",
    "Still here, just gathering my thoughts...",
    "Almost...",
    "Hang on...",
    "Just a little longer...",
    "Thinking it through...",
    "Stay with me...",
    "Working on a diaper bag...",
    "This place smells like a nursery...",
    "Where did I put the paci...",
    "One sec, someone's fussing...",
    "Hang on, checking the crib...",
    "Just a moment — wipes are in the other room...",
  ],
  poet: [
    "Mulling it over...",
    "Let the words settle...",
    "One moment...",
    "Turning it over...",
    "Still composing...",
    "Almost there...",
    "Patience, patience...",
    "Gathering the lines...",
    "Thinking...",
    "Just a moment...",
  ],
  default: [
    "Working on it...",
    "Thinking it over...",
    "One moment...",
    "Give me a sec...",
    "Still on it...",
    "Almost there...",
    "Hang tight...",
    "Putting it together...",
    "Checking a few things...",
    "Still working...",
  ],
};

function getLoadingPhrase(modeId: string | undefined): string {
  const key = modeId === 'roleplay' ? 'roleplay' : modeId === 'poet' ? 'poet' : 'default';
  const list = LOADING_PHRASES[key] ?? LOADING_PHRASES.default;
  return list[Math.floor(Math.random() * list.length)];
}

export function ChatTab() {
  const [input, setInput] = useState('');
  const [loadingPhrase, setLoadingPhrase] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { chatMessages, chatLoading, chatError, sendMessage, clearChat, sessionAgent } = useAppStore();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  // Pick one loading phrase when loading starts so it doesn’t change mid-request
  useEffect(() => {
    if (chatLoading) {
      setLoadingPhrase((prev) => prev || getLoadingPhrase(sessionAgent?.mode_id));
    } else {
      setLoadingPhrase('');
    }
  }, [chatLoading, sessionAgent?.mode_id]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || chatLoading) return;
    
    const message = input.trim();
    setInput('');
    await sendMessage(message);
  };

  return (
    <div className="chat-container h-full">
      <div className="flex items-center justify-between p-4 border-b border-base-300">
        <div>
          <h2 className="text-xl font-bold">Chat with Glitch</h2>
          <p className="text-sm text-base-content/60">
            Talk directly to your AI orchestrator
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={clearChat}
          disabled={chatMessages.length === 0}
          title="Clear chat"
        >
          <Trash2 size={18} />
          Clear
        </button>
      </div>

      <div className="chat-messages">
        {chatMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-base-content/60">
            <div className="w-16 h-16 rounded-full bg-primary/20 flex items-center justify-center mb-4">
              <span className="text-3xl">G</span>
            </div>
            <p className="text-lg font-medium">Welcome to Glitch</p>
            <p className="text-sm">Start a conversation with your AI agent</p>
          </div>
        ) : (
          <div className="space-y-4">
            {chatMessages.map((message) => (
              <div
                key={message.id}
                className={`chat ${message.role === 'user' ? 'chat-end' : 'chat-start'}`}
              >
                <div className="chat-image avatar">
                  <div className={`w-10 rounded-full ${
                    message.role === 'user' ? 'bg-secondary' : 'bg-primary'
                  } flex items-center justify-center`}>
                    <span className="text-primary-content font-bold">
                      {message.role === 'user' ? 'U' : 'G'}
                    </span>
                  </div>
                </div>
                <div className="chat-header mb-1">
                  {message.role === 'user' ? 'You' : 'Glitch'}
                  <time className="text-xs opacity-50 ml-2">
                    {message.timestamp.toLocaleTimeString()}
                  </time>
                </div>
                <div className={`chat-bubble ${
                  message.role === 'user' ? 'chat-bubble-secondary' : 'chat-bubble-primary'
                }`}>
                  <div className="markdown-content">
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  </div>
                </div>
                {message.metrics && message.metrics.duration_seconds !== undefined && (
                  <div className="chat-footer opacity-50 text-xs mt-1">
                    {message.metrics.duration_seconds.toFixed(2)}s
                    {message.metrics.token_usage?.total_tokens !== undefined && (
                      <> · {message.metrics.token_usage.total_tokens} tokens</>
                    )}
                    {message.metrics.cycle_count !== undefined && (
                      <> · {message.metrics.cycle_count} cycles</>
                    )}
                  </div>
                )}
              </div>
            ))}
            {chatLoading && (
              <div className="chat chat-start">
                <div className="chat-image avatar">
                  <div className="w-10 rounded-full bg-primary flex items-center justify-center">
                    <span className="text-primary-content font-bold">G</span>
                  </div>
                </div>
                <div className="chat-bubble chat-bubble-primary flex items-center gap-2">
                  <Loader2 className="animate-spin shrink-0" size={20} />
                  <span>{loadingPhrase || getLoadingPhrase(sessionAgent?.mode_id)}</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {chatError && (
        <div className="px-4">
          <div className="alert alert-error">
            <span>{chatError}</span>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="chat-input">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            className="input input-bordered flex-1"
            disabled={chatLoading}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!input.trim() || chatLoading}
          >
            {chatLoading ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <Send size={20} />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
