package admin

import (
	"context"
	"strconv"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/handler/dto"
	"github.com/Wei-Shaw/sub2api/internal/pkg/pagination"
	"github.com/Wei-Shaw/sub2api/internal/pkg/response"
	"github.com/Wei-Shaw/sub2api/internal/server/middleware"
	"github.com/Wei-Shaw/sub2api/internal/service"

	"github.com/gin-gonic/gin"
)

// AdminAPIKeyHandler handles admin API key management
type AdminAPIKeyHandler struct {
	adminService  service.AdminService
	apiKeyService *service.APIKeyService
}

// NewAdminAPIKeyHandler creates a new admin API key handler
func NewAdminAPIKeyHandler(adminService service.AdminService, apiKeyServices ...*service.APIKeyService) *AdminAPIKeyHandler {
	var apiKeyService *service.APIKeyService
	if len(apiKeyServices) > 0 {
		apiKeyService = apiKeyServices[0]
	}
	return &AdminAPIKeyHandler{
		adminService:  adminService,
		apiKeyService: apiKeyService,
	}
}

func NewAdminAPIKeyHandlerWithService(adminService service.AdminService, apiKeyService *service.APIKeyService) *AdminAPIKeyHandler {
	return NewAdminAPIKeyHandler(adminService, apiKeyService)
}

// Admin API key CRUD is intentionally nested under a target user. The admin
// credential authenticates the operator; the target user is never inferred
// from or substituted into the authentication context.
type adminCreateAPIKeyRequest struct {
	Name          string   `json:"name" binding:"required"`
	GroupID       *int64   `json:"group_id"`
	CustomKey     *string  `json:"custom_key"`
	IPWhitelist   []string `json:"ip_whitelist"`
	IPBlacklist   []string `json:"ip_blacklist"`
	Quota         float64  `json:"quota"`
	ExpiresInDays *int     `json:"expires_in_days"`
	RateLimit5h   float64  `json:"rate_limit_5h"`
	RateLimit1d   float64  `json:"rate_limit_1d"`
	RateLimit7d   float64  `json:"rate_limit_7d"`
}

type adminUpdateAPIKeyRequest struct {
	Name                *string   `json:"name"`
	GroupID             *int64    `json:"group_id"`
	Status              *string   `json:"status"`
	IPWhitelist         *[]string `json:"ip_whitelist"`
	IPBlacklist         *[]string `json:"ip_blacklist"`
	Quota               *float64  `json:"quota"`
	ExpiresAt           *string   `json:"expires_at"`
	ResetQuota          *bool     `json:"reset_quota"`
	RateLimit5h         *float64  `json:"rate_limit_5h"`
	RateLimit1d         *float64  `json:"rate_limit_1d"`
	RateLimit7d         *float64  `json:"rate_limit_7d"`
	ResetRateLimitUsage *bool     `json:"reset_rate_limit_usage"`
}

func (h *AdminAPIKeyHandler) targetUserID(c *gin.Context) (int64, error) {
	return strconv.ParseInt(c.Param("id"), 10, 64)
}

func (h *AdminAPIKeyHandler) ListByUser(c *gin.Context) {
	userID, err := h.targetUserID(c)
	if err != nil || userID <= 0 {
		response.BadRequest(c, "Invalid user ID")
		return
	}
	page, pageSize := response.ParsePagination(c)
	filters := service.APIKeyListFilters{Search: c.Query("search"), Status: c.Query("status")}
	if raw := c.Query("group_id"); raw != "" {
		id, parseErr := strconv.ParseInt(raw, 10, 64)
		if parseErr != nil {
			response.BadRequest(c, "Invalid group_id")
			return
		}
		filters.GroupID = &id
	}
	keys, result, err := h.apiKeyService.List(c.Request.Context(), userID, servicePagination(page, pageSize, c.Query("sort_by"), c.Query("sort_order")), filters)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	out := make([]*dto.APIKey, 0, len(keys))
	for i := range keys {
		out = append(out, dto.APIKeyFromService(&keys[i]))
	}
	response.Paginated(c, out, result.Total, page, pageSize)
}

func servicePagination(page, pageSize int, sortBy, sortOrder string) pagination.PaginationParams {
	return pagination.PaginationParams{Page: page, PageSize: pageSize, SortBy: sortBy, SortOrder: sortOrder}
}

func (h *AdminAPIKeyHandler) CreateForUser(c *gin.Context) {
	userID, err := h.targetUserID(c)
	if err != nil || userID <= 0 {
		response.BadRequest(c, "Invalid user ID")
		return
	}
	var req adminCreateAPIKeyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	payload := service.CreateAPIKeyRequest{Name: req.Name, GroupID: req.GroupID, CustomKey: req.CustomKey, IPWhitelist: req.IPWhitelist, IPBlacklist: req.IPBlacklist, Quota: req.Quota, ExpiresInDays: req.ExpiresInDays, RateLimit5h: req.RateLimit5h, RateLimit1d: req.RateLimit1d, RateLimit7d: req.RateLimit7d}
	execute := func(ctx context.Context) (any, error) {
		created, createErr := h.apiKeyService.Create(ctx, userID, payload)
		if createErr != nil {
			return nil, createErr
		}
		return dto.APIKeyFromService(created), nil
	}
	coordinator := service.DefaultIdempotencyCoordinator()
	if coordinator == nil {
		created, createErr := execute(c.Request.Context())
		if createErr != nil {
			response.ErrorFrom(c, createErr)
			return
		}
		response.Success(c, created)
		return
	}
	actorScope := "admin"
	if subject, ok := middleware.GetAuthSubjectFromContext(c); ok {
		actorScope = "admin:" + strconv.FormatInt(subject.UserID, 10)
	}
	result, err := coordinator.Execute(c.Request.Context(), service.IdempotencyExecuteOptions{Scope: "admin.users.keys.create", ActorScope: actorScope, Method: c.Request.Method, Route: c.FullPath(), IdempotencyKey: c.GetHeader("Idempotency-Key"), Payload: map[string]any{"user_id": userID, "request": payload}, TTL: service.DefaultWriteIdempotencyTTL(), RequireKey: true}, execute)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	if result.Replayed {
		c.Header("X-Idempotency-Replayed", "true")
	}
	response.Success(c, result.Data)
}

func (h *AdminAPIKeyHandler) GetForUser(c *gin.Context) {
	userID, err := h.targetUserID(c)
	if err != nil || userID <= 0 {
		response.BadRequest(c, "Invalid user ID")
		return
	}
	id, err := strconv.ParseInt(c.Param("key_id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "Invalid API key ID")
		return
	}
	key, err := h.apiKeyService.GetByID(c.Request.Context(), id)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	if key.UserID != userID {
		response.NotFound(c, "API key not found")
		return
	}
	response.Success(c, dto.APIKeyFromService(key))
}

func (h *AdminAPIKeyHandler) UpdateForUser(c *gin.Context) {
	userID, err := h.targetUserID(c)
	if err != nil || userID <= 0 {
		response.BadRequest(c, "Invalid user ID")
		return
	}
	id, err := strconv.ParseInt(c.Param("key_id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "Invalid API key ID")
		return
	}
	var req adminUpdateAPIKeyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	update := service.UpdateAPIKeyRequest{Name: req.Name, GroupID: req.GroupID, Status: req.Status, IPWhitelist: req.IPWhitelist, IPBlacklist: req.IPBlacklist, Quota: req.Quota, RateLimit5h: req.RateLimit5h, RateLimit1d: req.RateLimit1d, RateLimit7d: req.RateLimit7d, ResetQuota: req.ResetQuota, ResetRateLimitUsage: req.ResetRateLimitUsage}
	if req.ExpiresAt != nil {
		if *req.ExpiresAt == "" {
			update.ClearExpiration = true
		} else {
			t, parseErr := time.Parse(time.RFC3339, *req.ExpiresAt)
			if parseErr != nil {
				response.BadRequest(c, "Invalid expires_at")
				return
			}
			update.ExpiresAt = &t
		}
	}
	key, err := h.apiKeyService.Update(c.Request.Context(), id, userID, update)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	response.Success(c, dto.APIKeyFromService(key))
}

func (h *AdminAPIKeyHandler) DeleteForUser(c *gin.Context) {
	userID, err := h.targetUserID(c)
	if err != nil || userID <= 0 {
		response.BadRequest(c, "Invalid user ID")
		return
	}
	id, err := strconv.ParseInt(c.Param("key_id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "Invalid API key ID")
		return
	}
	if err := h.apiKeyService.Delete(c.Request.Context(), id, userID); err != nil {
		response.ErrorFrom(c, err)
		return
	}
	response.Success(c, gin.H{"message": "API key deleted successfully"})
}

// AdminUpdateAPIKeyGroupRequest represents the request to update an API key.
type AdminUpdateAPIKeyGroupRequest struct {
	GroupID             *int64 `json:"group_id"`               // nil=不修改, 0=解绑, >0=绑定到目标分组
	ResetRateLimitUsage *bool  `json:"reset_rate_limit_usage"` // true=重置 5h/1d/7d 限速用量
}

// UpdateGroup handles updating an API key's admin-managed fields.
// PUT /api/v1/admin/api-keys/:id
func (h *AdminAPIKeyHandler) UpdateGroup(c *gin.Context) {
	keyID, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "Invalid API key ID")
		return
	}

	var req AdminUpdateAPIKeyGroupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "Invalid request: "+err.Error())
		return
	}

	var resetKey *service.APIKey
	if req.ResetRateLimitUsage != nil && *req.ResetRateLimitUsage {
		resetKey, err = h.adminService.AdminResetAPIKeyRateLimitUsage(c.Request.Context(), keyID)
		if err != nil {
			response.ErrorFrom(c, err)
			return
		}
	}

	result, err := h.adminService.AdminUpdateAPIKeyGroupID(c.Request.Context(), keyID, req.GroupID)
	if err != nil {
		response.ErrorFrom(c, err)
		return
	}
	if resetKey != nil && req.GroupID == nil {
		result.APIKey = resetKey
	}

	resp := struct {
		APIKey                 *dto.APIKey `json:"api_key"`
		AutoGrantedGroupAccess bool        `json:"auto_granted_group_access"`
		GrantedGroupID         *int64      `json:"granted_group_id,omitempty"`
		GrantedGroupName       string      `json:"granted_group_name,omitempty"`
	}{
		APIKey:                 dto.APIKeyFromService(result.APIKey),
		AutoGrantedGroupAccess: result.AutoGrantedGroupAccess,
		GrantedGroupID:         result.GrantedGroupID,
		GrantedGroupName:       result.GrantedGroupName,
	}
	response.Success(c, resp)
}
