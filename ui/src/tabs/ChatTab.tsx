import { useState, useRef, useEffect } from 'react';
import { Send, Trash2, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useAppStore } from '../store/useAppStore';

export function ChatTab() {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { chatMessages, chatLoading, chatError, sendMessage, clearChat } = useAppStore();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

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
                <div className="chat-bubble chat-bubble-primary">
                  <Loader2 className="animate-spin" size={20} />
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
