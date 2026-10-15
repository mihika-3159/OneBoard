import React, { useState } from 'react';
import { Send, Bot, Sparkles, Terminal, ShieldAlert, Cpu } from 'lucide-react';
import { api } from '../services/api';

export const FounderCommandTab: React.FC = () => {
  const [inputCommand, setInputCommand] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: 'founder' | 'os'; content: string; model?: string; simulated?: boolean }>>([
    {
      role: 'os',
      content:
        'Welcome to the Founder Command Center. I coordinate Northstar Studio across your CRM, financial ledger, documents, and active commitments. What strategic or operational objective would you like to review?',
    },
  ]);

  const quickPrompts = [
    "What's the most important thing I should work on today?",
    "Find inconsistencies in our pricing documents.",
    "Which customer commitments are overdue or at risk?",
    "Prepare this week's executive board agenda.",
    "Compare actual expenses against our operating budget.",
  ];

  const handleSend = async (text?: string) => {
    const cmd = text || inputCommand;
    if (!cmd.trim()) return;

    const userMsg = { role: 'founder' as const, content: cmd };
    setMessages((prev) => [...prev, userMsg]);
    setInputCommand('');
    setIsLoading(true);

    try {
      const res = await api.executeCommand(cmd);
      setMessages((prev) => [
        ...prev,
        {
          role: 'os',
          content: res.response || 'Command executed.',
          model: res.model,
          simulated: res.simulated,
        },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'os',
          content: 'Unable to communicate with local model gateway. Please ensure API server is active.',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-[calc(100vh-140px)] flex flex-col space-y-4">
      {/* Header Info */}
      <div className="p-4 rounded-xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400">
            <Terminal className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white">Founder Command Center</h2>
            <p className="text-xs text-slate-400">Unified conversational control backed by 3-tier business memory</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
          <Cpu className="w-3.5 h-3.5 text-indigo-400" />
          <span>Gateway: Ollama (Balanced Profile: qwen2.5:7b)</span>
        </div>
      </div>

      {/* Suggested Quick Prompts */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
        <span className="text-slate-400 font-medium whitespace-nowrap flex items-center gap-1">
          <Sparkles className="w-3.5 h-3.5 text-amber-400" /> Quick Inquiries:
        </span>
        {quickPrompts.map((p, idx) => (
          <button
            key={idx}
            onClick={() => handleSend(p)}
            className="px-3 py-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/50 whitespace-nowrap transition"
          >
            {p}
          </button>
        ))}
      </div>

      {/* Chat Messages Log */}
      <div className="flex-1 overflow-y-auto space-y-4 p-4 rounded-2xl glass-panel">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex gap-3 max-w-3xl ${m.role === 'founder' ? 'ml-auto justify-end' : ''}`}
          >
            {m.role === 'os' && (
              <div className="w-8 h-8 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center shrink-0 mt-1">
                <Bot className="w-4 h-4" />
              </div>
            )}
            <div
              className={`p-4 rounded-2xl text-sm leading-relaxed ${
                m.role === 'founder'
                  ? 'bg-indigo-600 text-white rounded-br-none shadow-md shadow-indigo-600/10'
                  : 'bg-slate-900/90 text-slate-200 rounded-tl-none border border-slate-800/80 shadow-md'
              }`}
            >
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.model && (
                <div className="mt-2.5 pt-2 border-t border-slate-800 flex items-center justify-between text-[11px] font-mono text-slate-500">
                  <span>Model: {m.model}</span>
                  {m.simulated && (
                    <span className="text-amber-400/80 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                      local simulator
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex gap-3 max-w-xl">
            <div className="w-8 h-8 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 animate-spin" />
            </div>
            <div className="p-4 rounded-2xl bg-slate-900 text-slate-400 text-sm border border-slate-800 rounded-tl-none flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping"></span>
              Synthesizing response across database, memory chunks, and financial ledger...
            </div>
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="p-2 rounded-2xl glass-panel flex items-center gap-2">
        <input
          type="text"
          value={inputCommand}
          onChange={(e) => setInputCommand(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask a question or delegate a task (e.g., 'Check overdue commitments and draft updates')..."
          className="flex-1 bg-transparent px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none"
        />
        <button
          onClick={() => handleSend()}
          disabled={isLoading || !inputCommand.trim()}
          className="p-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl transition shadow-md shadow-indigo-600/20"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
