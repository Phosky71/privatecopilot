import { useState, useEffect, useCallback, useRef } from 'react'
import SettingsModal from './components/SettingsModal'
import FileBrowserModal from './components/FileBrowserModal'
import ChatMessage, { type Message } from './components/ChatMessage'
import { API_URL } from './config'
import {
  type Workspace,
  type ModelInfo,
  type ModelsResponse,
  type GitStatus,
  type GitRepoStatus,
  type GitInitPolicy,
  type IndexProgress,
  type ProviderStatus,
} from './types'

function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isIndexing, setIsIndexing] = useState(false)
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([])
  const [providersStatus, setProvidersStatus] = useState<ProviderStatus[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string>('')
  const [showSettings, setShowSettings] = useState(false)
  const [browserMode, setBrowserMode] = useState<'open-workspace' | 'folder' | 'file' | null>(null)
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [gitInitPolicy, setGitInitPolicy] = useState<GitInitPolicy>('ask')
  const [indexProgress, setIndexProgress] = useState<IndexProgress | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const fetchGitStatus = useCallback(async () => {
    if (!activeWorkspace) return
    try {
      const res = await fetch(`${API_URL}/git/status?workspace_id=${activeWorkspace.id}`)
      if (!res.ok) {
        console.error('Failed to fetch git status', res.status)
        return
      }
      const data: GitStatus = await res.json()
      setGitStatus(data)
    } catch (err: unknown) {
      console.error(err)
    }
  }, [activeWorkspace])

  const fetchGitConfig = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/git/config`)
      if (!res.ok) return
      const data = await res.json()
      if (data.git_init_policy) {
        setGitInitPolicy(data.git_init_policy as GitInitPolicy)
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }, [])

  const handleGitInitPolicyChange = async (policy: GitInitPolicy) => {
    try {
      const res = await fetch(`${API_URL}/git/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ git_init_policy: policy }),
      })
      if (!res.ok) {
        console.error('Failed to update git config', res.status)
        return
      }
      const data = await res.json()
      setGitInitPolicy(data.git_init_policy as GitInitPolicy)
      await fetchGitStatus()
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleInitializeGit = async (repoPath?: string) => {
    if (!activeWorkspace) return
    if (gitInitPolicy === 'ask' && !confirm('Initialize a Git repository in this folder?')) {
      return
    }
    try {
      const res = await fetch(`${API_URL}/git/init`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: activeWorkspace.id, repo_path: repoPath }),
      })
      if (!res.ok) {
        console.error('Failed to initialize git', res.status)
        return
      }
      await fetchGitStatus()
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const fetchModels = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/model`)
      if (!res.ok) {
        console.error('Failed to fetch models', res.status)
        return
      }
      const data: ModelsResponse = await res.json()
      setAvailableModels(data.models || [])
      setProvidersStatus(data.providers_status || [])
      if (activeWorkspace) {
        const wsModel = (data.models || []).find((m: ModelInfo) => m.model === activeWorkspace.model)
        if (wsModel) {
          setSelectedModelId(wsModel.id)
        }
      } else {
        const defaultModel = (data.models || []).find((m: ModelInfo) => m.model === data.default)
        if (defaultModel) {
          setSelectedModelId(defaultModel.id)
        }
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }, [activeWorkspace])

  const refreshModels = useCallback(async () => {
    await fetchModels()
  }, [fetchModels])

  const handleWorkspaceSwitch = useCallback(async (ws: Workspace) => {
    setActiveWorkspace(ws)
    setMessages([])
    setIndexProgress(null)
    try {
      const res = await fetch(`${API_URL}/workspace/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: ws.id }),
      })
      if (!res.ok) {
        console.error('Failed to switch workspace', res.status)
        return
      }
      const data = await res.json()
      const switched = data.active_workspace as Workspace
      setActiveWorkspace(switched)
      // Load chat history
      try {
        const hRes = await fetch(`${API_URL}/chat/history?workspace_id=${switched.id}`)
        if (hRes.ok) {
          const hData = await hRes.json()
          const msgs: Message[] = (hData.messages || []).map((m: { role: string; content: string }) => ({
            role: m.role,
            content: m.content,
            status: 'done',
          }))
          setMessages(msgs)
        }
      } catch (err: unknown) {
        console.error(err)
      }
      // Restore index progress
      try {
        const pRes = await fetch(`${API_URL}/index/status?workspace_id=${switched.id}`)
        if (pRes.ok) {
          const pData: IndexProgress = await pRes.json()
          setIndexProgress(pData)
        }
      } catch (err: unknown) {
        console.error(err)
      }
      const wsModel = availableModels.find((m: ModelInfo) => m.model === switched.model)
      if (wsModel) {
        setSelectedModelId(wsModel.id)
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }, [availableModels])

  const fetchWorkspaces = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/workspace`)
      if (!res.ok) {
        console.error('Failed to fetch workspaces', res.status)
        return
      }
      const data: Workspace[] = await res.json()
      setWorkspaces(data)
      if (data.length > 0 && !activeWorkspace) {
        void handleWorkspaceSwitch(data[0])
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }, [activeWorkspace, handleWorkspaceSwitch])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      await Promise.resolve()
      if (cancelled) return
      await fetchGitStatus()
    })()
    const interval = setInterval(() => {
      void fetchGitStatus()
    }, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [fetchGitStatus])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      await Promise.resolve()
      if (cancelled) return
      await fetchGitConfig()
      await fetchWorkspaces()
      await fetchModels()
    })()
    return () => {
      cancelled = true
    }
  }, [fetchGitConfig, fetchWorkspaces, fetchModels])

  const handleOpenWorkspace = async (folderPath: string) => {
    try {
      const res = await fetch(`${API_URL}/workspace/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: folderPath }),
      })
      if (!res.ok) {
        console.error('Failed to open workspace', res.status)
        return
      }
      const ws: Workspace = await res.json()
      await fetchWorkspaces()
      await handleWorkspaceSwitch(ws)
      try {
        const pRes = await fetch(`${API_URL}/index/status?workspace_id=${ws.id}`)
        if (pRes.ok) {
          const pData: IndexProgress = await pRes.json()
          setIndexProgress(pData)
          if (!pData.has_indexed_data && pData.status !== 'running') {
            void handleIndexWorkspace()
          }
        }
      } catch (err: unknown) {
        console.error(err)
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleIndexWorkspace = async () => {
    if (!activeWorkspace) return
    // Close previous stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    setIsIndexing(true)
    try {
      const res = await fetch(`${API_URL}/index/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: activeWorkspace.id }),
      })
      if (!res.ok) {
        console.error('Failed to start indexing', res.status)
        setIsIndexing(false)
        return
      }
      const snapshot: IndexProgress = await res.json()
      setIndexProgress(snapshot)

      const es = new EventSource(`${API_URL}/index/stream?workspace_id=${activeWorkspace.id}`)
      eventSourceRef.current = es
      es.onmessage = (event) => {
        try {
          const data: IndexProgress = JSON.parse(event.data)
          setIndexProgress(data)
          if (data.status === 'completed' || data.status === 'error') {
            es.close()
            eventSourceRef.current = null
            setIsIndexing(false)
          }
        } catch (err: unknown) {
          console.error(err)
        }
      }
      es.onerror = () => {
        es.close()
        eventSourceRef.current = null
        setIsIndexing(false)
      }
    } catch (err: unknown) {
      console.error(err)
      setIsIndexing(false)
    }
  }

  const handleCloseIndexProgress = () => {
    setIndexProgress(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || !activeWorkspace) return

    const userMessage: Message = { role: 'user', content: input }
    setMessages(prev => [...prev, userMessage])
    setInput('')

    const aiMessage: Message = { role: 'assistant', content: '', status: 'thinking' }
    setMessages(prev => [...prev, aiMessage])

    try {
      const history = messages
        .filter(m => m.status !== 'thinking' && m.content && !m.content.startsWith('Error:'))
        .map(m => ({ role: m.role, content: m.content }))

      const response = await fetch(`${API_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: activeWorkspace.id, query: userMessage.content, history }),
      })

      if (!response.ok || !response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      let done = false
      let buffer = ''
      let streamError: string | null = null

      while (!done) {
        const { value, done: readerDone } = await reader.read()
        done = readerDone
        if (value) {
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let chunkContent = ''
          for (const line of lines) {
            const trimmedLine = line.trim()
            if (trimmedLine.startsWith('data: ')) {
              const jsonStr = trimmedLine.substring(6)
              if (!jsonStr) continue
              try {
                const data = JSON.parse(jsonStr) as { response?: string; error?: string; done?: boolean }
                if (data.error) {
                  streamError = data.error
                } else if (data.response !== undefined) {
                  chunkContent += data.response
                }
                if (data.done) {
                  done = true
                }
              } catch {
                // Ignore silent JSON parse errors for completely broken lines
              }
            }
          }

          if (streamError) {
            setMessages(prev => {
              const newMessages = [...prev]
              if (newMessages.length > 0) {
                const lastMsg = newMessages[newMessages.length - 1]
                lastMsg.content = `Error: ${streamError}`
                lastMsg.status = 'done'
              }
              return newMessages
            })
            break
          }

          if (chunkContent) {
            setMessages(prev => {
              const newMessages = [...prev]
              const lastMsg = { ...newMessages[newMessages.length - 1] }
              lastMsg.content += chunkContent
              lastMsg.status = 'streaming'
              newMessages[newMessages.length - 1] = lastMsg
              return newMessages
            })
          }
        }
      }

      setMessages(prev => {
        const newMessages = [...prev]
        if (newMessages.length > 0) {
          newMessages[newMessages.length - 1].status = 'done'
        }
        return newMessages
      })
    } catch (err: unknown) {
      console.error(err)
      setMessages(prev => {
        const newMessages = [...prev]
        if (newMessages.length > 0) {
          const lastMsg = newMessages[newMessages.length - 1]
          lastMsg.content = 'Error communicating with AI assistant.'
          lastMsg.status = 'done'
        }
        return newMessages
      })
    }
  }

  const handleModelChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const modelId = e.target.value
    setSelectedModelId(modelId)
    try {
      const res = await fetch(`${API_URL}/model/set`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_id: modelId,
          workspace_id: activeWorkspace?.id,
        }),
      })
      if (!res.ok) {
        console.error('Failed to set model', res.status)
        return
      }
      if (activeWorkspace) {
        setActiveWorkspace({ ...activeWorkspace, model: modelId })
      }
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleUpdateWorkspaceName = async (name: string) => {
    if (!activeWorkspace) return
    try {
      const res = await fetch(`${API_URL}/workspace/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: activeWorkspace.id, name }),
      })
      if (!res.ok) {
        console.error('Failed to update workspace name', res.status)
        return
      }
      const ws: Workspace = await res.json()
      setActiveWorkspace(ws)
      await fetchWorkspaces()
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleClearChat = async () => {
    if (!activeWorkspace) return
    try {
      const res = await fetch(`${API_URL}/chat/history?workspace_id=${activeWorkspace.id}`, { method: 'DELETE' })
      if (!res.ok) {
        console.error('Failed to clear chat', res.status)
        return
      }
      setMessages([])
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleDeleteWorkspace = async () => {
    if (!activeWorkspace) return
    try {
      const res = await fetch(`${API_URL}/workspace/${activeWorkspace.id}`, { method: 'DELETE' })
      if (!res.ok) {
        console.error('Failed to delete workspace', res.status)
        return
      }
      setActiveWorkspace(null)
      setShowSettings(false)
      await fetchWorkspaces()
    } catch (err: unknown) {
      console.error(err)
    }
  }

  const handleModifyWorkspaceList = async (endpoint: string, payload: Record<string, unknown>) => {
    try {
      const res = await fetch(`${API_URL}/workspace/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        console.error('Failed to modify workspace list', res.status)
        return
      }
      const ws: Workspace = await res.json()
      setActiveWorkspace(ws)
    } catch (err: unknown) {
      console.error(err)
    }
  }

  return (
    <div className="flex h-screen bg-gray-900 text-gray-100 font-sans">
      <div className="w-64 bg-gray-800 border-r border-gray-700 p-4 flex flex-col">
        <h1 className="text-xl font-bold mb-6 text-blue-400">PrivateCopilot</h1>

        <div className="flex-1">
          <h2 className="text-xs uppercase text-gray-400 font-semibold mb-3">Workspaces</h2>
          <div className="space-y-2">
            {workspaces.length === 0 ? (
              <p className="text-sm text-gray-500">No workspaces yet.</p>
            ) : (
              workspaces.map(ws => (
                <button
                  key={ws.id}
                  onClick={() => void handleWorkspaceSwitch(ws)}
                  className={`w-full text-left px-3 py-2 rounded-md transition-colors ${activeWorkspace?.id === ws.id ? 'bg-blue-600 text-white' : 'hover:bg-gray-700 text-gray-300'}`}
                >
                  {ws.name}
                </button>
              ))
            )}
          </div>
        </div>

        <div className="flex-1 mt-6 border-t border-gray-700 pt-4 overflow-y-auto">
          <h2 className="text-xs uppercase text-gray-400 font-semibold mb-3">Git Status</h2>
          {gitStatus ? (
            <div className="space-y-2 text-sm bg-gray-900 p-3 rounded-md border border-gray-700">
              {(gitStatus.repositories && gitStatus.repositories.length > 0 ? gitStatus.repositories : [gitStatus as unknown as GitRepoStatus]).map((repo, idx) => (
                <div key={idx} className="border-b border-gray-800 pb-2 last:border-0">
                  <div className="text-xs font-bold text-gray-300 truncate">{repo.name}</div>
                  {repo.initialized === false ? (
                    <>
                      <div className="text-gray-400 text-xs">Not a Git repository</div>
                      {gitInitPolicy !== 'never' && (
                        <button
                          onClick={() => void handleInitializeGit(repo.repo_path)}
                          className="mt-1 px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium"
                        >
                          Initialize Git
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 text-blue-400">
                        <span className="font-mono text-xs font-bold truncate">{repo.branch || 'N/A'}</span>
                      </div>
                      <div className="text-gray-400 text-xs mt-1">
                        Pending Changes: {repo.pending_changes?.length || 0}
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 italic">No valid workspace or repo loaded.</p>
          )}
        </div>

        <button
          onClick={() => setBrowserMode('open-workspace')}
          className="mt-4 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors flex items-center justify-center font-medium shadow-sm"
        >
          <span className="mr-2">+</span> Open Workspace Folder
        </button>
      </div>

      <div className="flex-1 flex flex-col relative">
        <div className="h-16 border-b border-gray-800 flex items-center justify-between px-6 bg-gray-900 z-10 shadow-sm">
          <div>
            <h2 className="text-lg font-semibold text-gray-200">
              {activeWorkspace ? activeWorkspace.name : 'Select a workspace'}
            </h2>
            {activeWorkspace?.folders?.[0] && (
              <p className="text-xs text-gray-500 font-mono truncate">{activeWorkspace.folders[0]}</p>
            )}
          </div>
          <div className="flex items-center space-x-3">
            {availableModels.length > 0 ? (
              <select
                value={selectedModelId}
                onChange={e => void handleModelChange(e)}
                className="bg-gray-800 text-sm text-gray-200 border border-gray-700 rounded-md px-3 py-1.5 focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                {availableModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            ) : (
              <span className="text-xs text-yellow-400">No LLM models detected</span>
            )}
            <button
              onClick={() => void refreshModels()}
              title="Refresh models"
              className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm"
            >
              ↻
            </button>
            {activeWorkspace && indexProgress?.has_indexed_data && (
              <span className="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs">
                {indexProgress.known_indexed_files} indexed
              </span>
            )}
            {activeWorkspace && indexProgress && indexProgress.status !== 'running' && !indexProgress.has_indexed_data && (
              <span className="px-2 py-1 bg-amber-900/40 text-amber-300 rounded text-xs">
                Not indexed
              </span>
            )}
            {activeWorkspace && (
              <button
                onClick={() => void handleIndexWorkspace()}
                disabled={isIndexing}
                className="px-4 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm font-medium transition-colors disabled:opacity-50"
              >
                {isIndexing ? 'Indexing...' : 'Index Workspace'}
              </button>
            )}
            {activeWorkspace && messages.length > 0 && (
              <button
                onClick={() => void handleClearChat()}
                className="px-4 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm font-medium transition-colors"
              >
                Clear Chat
              </button>
            )}
            <button
              onClick={() => setShowSettings(true)}
              className="px-4 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md text-sm font-medium transition-colors"
            >
              Settings
            </button>
          </div>
        </div>

        {indexProgress && indexProgress.status !== 'idle' && (
          <div className="px-6 py-3 bg-gray-800 border-b border-gray-700">
            <div className="flex items-center justify-between text-xs text-gray-300 mb-1">
              <span>{indexProgress.phase} — {indexProgress.processed_files}/{indexProgress.total_files} ({indexProgress.percent}%)</span>
              <button onClick={handleCloseIndexProgress} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <div className="w-full bg-gray-700 rounded h-2 overflow-hidden">
              <div className="bg-blue-600 h-2" style={{ width: `${indexProgress.percent}%` }} />
            </div>
            {indexProgress.current_file && (
              <div className="text-xs text-gray-500 mt-1 truncate">{indexProgress.current_file}</div>
            )}
            {indexProgress.status === 'completed' && (
              <div className="text-xs text-green-400 mt-1">Indexed {indexProgress.indexed_files}, skipped {indexProgress.skipped_files}, failed {indexProgress.failed_files}, removed {indexProgress.removed_files}</div>
            )}
            {indexProgress.status === 'error' && (
              <div className="text-xs text-red-400 mt-1">{indexProgress.error}</div>
            )}
          </div>
        )}

        <div className="flex-1 p-6 overflow-y-auto space-y-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 space-y-4">
              <div className="w-16 h-16 bg-gray-800 rounded-full flex items-center justify-center text-blue-500">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <p className="text-lg font-medium">Ask a question about your codebase</p>
              {activeWorkspace && indexProgress && indexProgress.status !== 'running' && !indexProgress.has_indexed_data && (
                <button
                  onClick={() => void handleIndexWorkspace()}
                  className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-md text-sm font-medium"
                >
                  Index Now
                </button>
              )}
            </div>
          ) : (
            messages.map((msg, i) => (
              <ChatMessage
                key={i}
                message={msg}
                workspaceId={activeWorkspace?.id || ''}
                API_URL={API_URL}
                repositories={gitStatus?.repositories}
              />
            ))
          )}
        </div>

        <div className="p-4 bg-gray-900 border-t border-gray-800">
          <form className="max-w-4xl mx-auto flex shadow-sm" onSubmit={e => void handleSubmit(e)}>
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={!activeWorkspace}
              placeholder={activeWorkspace ? 'Ask anything...' : 'Select a workspace to chat'}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-l-lg px-5 py-3.5 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 transition-colors"
            />
            <button
              type="submit"
              disabled={!activeWorkspace || !input.trim()}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 px-6 py-3.5 rounded-r-lg font-medium transition-colors"
            >
              Send
            </button>
          </form>
        </div>
      </div>

      {showSettings && (
        <SettingsModal
          activeWorkspace={activeWorkspace}
          gitInitPolicy={gitInitPolicy}
          providersStatus={providersStatus}
          onClose={() => setShowSettings(false)}
          onUpdate={name => { if (activeWorkspace) void handleUpdateWorkspaceName(name) }}
          onDelete={() => { if (activeWorkspace) void handleDeleteWorkspace() }}
          onAddFolder={() => { if (activeWorkspace) setBrowserMode('folder') }}
          onRemoveFolder={(path: string) => { if (activeWorkspace) void handleModifyWorkspaceList('remove-folder', { workspace_id: activeWorkspace.id, folder_path: path }) }}
          onAddFile={() => { if (activeWorkspace) setBrowserMode('file') }}
          onRemoveFile={(path: string) => { if (activeWorkspace) void handleModifyWorkspaceList('remove-file', { workspace_id: activeWorkspace.id, file_path: path }) }}
          onGitInitPolicyChange={policy => void handleGitInitPolicyChange(policy)}
          onRefreshModels={() => void refreshModels()}
        />
      )}

      {browserMode && (activeWorkspace || browserMode === 'open-workspace') && (
        <FileBrowserModal
          API_URL={API_URL}
          mode={browserMode === 'open-workspace' ? 'folder' : (browserMode as 'folder' | 'file')}
          onClose={() => setBrowserMode(null)}
          onSelect={(path: string) => {
            if (browserMode === 'open-workspace') {
              void handleOpenWorkspace(path)
            } else if (activeWorkspace) {
              void handleModifyWorkspaceList(browserMode === 'folder' ? 'add-folder' : 'add-file', {
                workspace_id: activeWorkspace.id,
                [browserMode === 'folder' ? 'folder_path' : 'file_path']: path,
              })
            }
            setBrowserMode(null)
          }}
        />
      )}
    </div>
  )
}

export default App
