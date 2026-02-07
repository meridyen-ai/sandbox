/**
 * Data Sources Page - Main component for managing data source connections.
 * Combines the data source selector grid and connection form.
 */

import React, { useState, useEffect } from "react";
import {
  Database,
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Loader2,
  RefreshCw,
  ArrowLeft,
  AlertCircle,
  Settings2,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { DataSourceSelector } from "./DataSourceSelector";
import { ConnectionForm } from "./ConnectionForm";
import { TableColumnSelector } from "./TableColumnSelector";
import { CSVUploadWizard } from "./CSVUploadWizard";
import { ConnectionsListView } from "./ConnectionsListView";
import {
  HandlerInfo,
  listConnections,
  deleteConnection,
  testConnection,
  updateSelectedSchema,
  getSelectedSchema,
  SelectedSchema,
} from "../../utils/dataConnectorsApi";
import type { ConnectionInfo } from "../../utils/dataConnectorsApi";
import { useTranslation } from "../../hooks/useTranslation";
import { useAppSelector, useAppDispatch } from "../../store/hooks";
import { fetchSessions, createNewSession, deleteSession } from "../../store/slices/sessionsSlice";
import { fetchWorkspaces } from "../../store/slices/workspacesSlice";
import { MainLayout } from "../layout";
import { DeleteConfirmModal } from "../common/DeleteConfirmModal";

type ViewMode = "list" | "select" | "form" | "tables" | "csv-upload";

interface DataSourcesPageProps {
  embedded?: boolean; // When true, renders without page wrapper (for embedding in Settings)
}

export const DataSourcesPage: React.FC<DataSourcesPageProps> = ({ embedded = false }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const { sessions, currentSession } = useAppSelector((s) => s.sessions);
  const { workspaces } = useAppSelector((s) => s.workspaces);
  const { user } = useAppSelector((s) => s.auth);

  // Find the active workspace from the user's active_workspace_id
  const currentWorkspace = workspaces.find((w) => w.id === user?.active_workspace_id);

  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [selectedHandler, setSelectedHandler] = useState<HandlerInfo | null>(null);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingConnection, setDeletingConnection] = useState<number | null>(null);
  const [testingConnection, setTestingConnection] = useState<number | null>(null);
  const [connectionStatuses, setConnectionStatuses] = useState<
    Record<number, { connected: boolean; error?: string }>
  >({});
  // State for table/column selection flow
  const [pendingConnectionId, setPendingConnectionId] = useState<number | null>(null);
  const [pendingConnectionName, setPendingConnectionName] = useState<string>("");
  const [savingSchema, setSavingSchema] = useState(false);
  // State for editing existing connection's schema
  const [editingConnectionId, setEditingConnectionId] = useState<number | null>(null);
  const [editingConnectionName, setEditingConnectionName] = useState<string>("");
  const [existingSelectedSchema, setExistingSelectedSchema] = useState<SelectedSchema | undefined>(undefined);
  // State for delete confirmation modal
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [connectionToDelete, setConnectionToDelete] = useState<{ id: number; name: string } | null>(null);

  useEffect(() => {
    // Fetch workspaces if not already loaded
    if (workspaces.length === 0) {
      dispatch(fetchWorkspaces());
    }
    if (!embedded) {
      dispatch(fetchSessions());
    }
  }, [dispatch, embedded, workspaces.length]);

  useEffect(() => {
    // Load connections when workspace is available
    if (currentWorkspace?.id) {
      loadConnections();
    } else {
      setLoading(false);
    }
  }, [currentWorkspace?.id]);

  const loadConnections = async () => {
    if (!currentWorkspace?.id) {
      setConnections([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await listConnections(currentWorkspace.id);
      setConnections(data);
    } catch (err) {
      // If API is not available, show empty state
      setConnections([]);
      setError(err instanceof Error ? err.message : t("dataSources.errors.loadFailed") || "Failed to load connections");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectDataSource = (handler: HandlerInfo) => {
    setSelectedHandler(handler);
    // Use special CSV upload wizard for CSV files
    if (handler.name === "csv") {
      setViewMode("csv-upload");
    } else {
      setViewMode("form");
    }
  };

  const handleBack = () => {
    if (viewMode === "form" || viewMode === "csv-upload") {
      setViewMode("select");
      setSelectedHandler(null);
    } else if (viewMode === "tables") {
      // If we came from creating a new connection, go back to form or csv-upload
      // If we came from editing, go back to list
      if (editingConnectionId) {
        setViewMode("list");
        setEditingConnectionId(null);
        setEditingConnectionName("");
        setExistingSelectedSchema(undefined);
      } else if (selectedHandler?.name === "csv") {
        setViewMode("csv-upload");
      } else {
        setViewMode("form");
      }
    } else {
      setViewMode("list");
    }
  };

  // Called when the connection form successfully creates a connection
  // Now moves to table selection instead of finishing
  const handleConnectionCreated = (connectionId: number, connectionName: string) => {
    setPendingConnectionId(connectionId);
    setPendingConnectionName(connectionName);
    setViewMode("tables");
  };

  // Called when user confirms table/column selection
  const handleSchemaSelected = async (selectedSchema: SelectedSchema) => {
    if (!currentWorkspace?.id) return;

    const connectionId = editingConnectionId || pendingConnectionId;
    if (!connectionId) return;

    setSavingSchema(true);
    try {
      await updateSelectedSchema(currentWorkspace.id, connectionId, selectedSchema);
      // Success - reload connections and go back to list
      await loadConnections();
      setViewMode("list");
      // Reset state
      setPendingConnectionId(null);
      setPendingConnectionName("");
      setEditingConnectionId(null);
      setEditingConnectionName("");
      setExistingSelectedSchema(undefined);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("dataSources.errors.schemaSaveFailed") || "Failed to save selected schema"
      );
    } finally {
      setSavingSchema(false);
    }
  };

  // Called when user wants to edit the schema of an existing connection
  const handleEditSchema = async (connectionId: number, connectionName: string) => {
    if (!currentWorkspace?.id) return;

    try {
      const response = await getSelectedSchema(currentWorkspace.id, connectionId);
      setEditingConnectionId(connectionId);
      setEditingConnectionName(connectionName);
      setExistingSelectedSchema(response.selected_schema || {});
      setViewMode("tables");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("dataSources.errors.schemaLoadFailed") || "Failed to load existing schema selection"
      );
    }
  };


  const handleDeleteConnection = (connectionId: number, connectionName: string) => {
    if (!currentWorkspace?.id) return;
    setConnectionToDelete({ id: connectionId, name: connectionName });
    setDeleteModalOpen(true);
  };

  const confirmDeleteConnection = async () => {
    if (!currentWorkspace?.id || !connectionToDelete) return;

    setDeletingConnection(connectionToDelete.id);
    try {
      await deleteConnection(currentWorkspace.id, connectionToDelete.id);
      setConnections((prev) => prev.filter((c) => c.id !== connectionToDelete.id));
      setConnectionStatuses((prev) => {
        const newStatuses = { ...prev };
        delete newStatuses[connectionToDelete.id];
        return newStatuses;
      });
      setDeleteModalOpen(false);
      setConnectionToDelete(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("dataSources.errors.deleteFailed") || "Failed to delete connection");
    } finally {
      setDeletingConnection(null);
    }
  };

  const cancelDeleteConnection = () => {
    setDeleteModalOpen(false);
    setConnectionToDelete(null);
  };

  const handleTestConnection = async (connectionId: number) => {
    if (!currentWorkspace?.id) return;

    setTestingConnection(connectionId);
    try {
      const status = await testConnection(currentWorkspace.id, connectionId);
      setConnectionStatuses((prev) => ({
        ...prev,
        [connectionId]: {
          connected: status.success,
          error: status.message,
        },
      }));
    } catch (err) {
      setConnectionStatuses((prev) => ({
        ...prev,
        [connectionId]: {
          connected: false,
          error: err instanceof Error ? err.message : t("dataSources.errors.testFailed") || "Connection test failed",
        },
      }));
    } finally {
      setTestingConnection(null);
    }
  };

  // Sidebar handlers for standalone page
  const handleNewChat = async () => {
    await dispatch(createNewSession());
    navigate("/chat");
  };

  const handleSelectSession = (sessionId: number) => {
    navigate("/chat");
  };

  const handleDeleteSession = async (sessionId: number) => {
    await dispatch(deleteSession(sessionId));
  };

  const renderConnectionsList = () => (
    <ConnectionsListView
      onCreateConnection={() => setViewMode("select")}
      onEditSchema={handleEditSchema}
    />
  );

  const content = (
    <>
      {viewMode === "list" && renderConnectionsList()}
      {viewMode === "select" && (
        <div className="space-y-4">
          <button
            onClick={handleBack}
            className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t("common.back") || "Back"}
          </button>
          <DataSourceSelector
            onSelect={handleSelectDataSource}
            selectedHandler={selectedHandler?.name}
          />
        </div>
      )}
      {viewMode === "form" && selectedHandler && currentWorkspace?.id && (
        <ConnectionForm
          handler={selectedHandler}
          workspaceId={currentWorkspace.id}
          onBack={handleBack}
          onSuccess={handleConnectionCreated}
        />
      )}
      {viewMode === "tables" && currentWorkspace?.id && (pendingConnectionId || editingConnectionId) && (
        <TableColumnSelector
          workspaceId={currentWorkspace.id}
          connectionId={(editingConnectionId || pendingConnectionId)!}
          connectionName={editingConnectionName || pendingConnectionName}
          initialSelectedSchema={existingSelectedSchema}
          onBack={handleBack}
          onConfirm={handleSchemaSelected}
          loading={savingSchema}
        />
      )}
      {viewMode === "csv-upload" && currentWorkspace?.id && (
        <CSVUploadWizard
          workspaceId={currentWorkspace.id}
          onBack={handleBack}
          onSuccess={handleConnectionCreated}
        />
      )}

      {/* Delete Confirmation Modal */}
      <DeleteConfirmModal
        isOpen={deleteModalOpen}
        onClose={cancelDeleteConnection}
        onConfirm={confirmDeleteConnection}
        title={t("dataSources.deleteTitle")}
        message={t("dataSources.deleteConfirm")}
        itemName={connectionToDelete?.name}
        loading={deletingConnection === connectionToDelete?.id}
      />
    </>
  );

  // If embedded, just return the content
  if (embedded) {
    return content;
  }

  // Full page wrapper with unified layout
  return (
    <MainLayout
      sessions={sessions}
      currentSessionId={currentSession?.id}
      onSelectSession={handleSelectSession}
      onNewChat={handleNewChat}
      onDeleteSession={handleDeleteSession}
    >
      <main className="flex-1 overflow-auto p-6 bg-slate-50 dark:bg-dashboard-bg">
        <div className="max-w-5xl mx-auto">
          <div className="bg-white dark:bg-dashboard-surface rounded-2xl shadow-sm border border-slate-200 dark:border-dashboard-border p-6">
            {content}
          </div>
        </div>
      </main>
    </MainLayout>
  );
};
