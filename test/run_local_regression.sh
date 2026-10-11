#!/usr/bin/env bash
set -euo pipefail

# Repository-local evidence for the implementation described in §1.5/§9.
# This does not contact an upstream provider or consume subscription quota.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/backend"

go test ./internal/pkg/apicompat -count=1
go test -tags=unit ./internal/config -run 'Test(OpenAIChatContract|.*ChatContract)' -count=1
go test -tags=unit ./internal/service -run 'Test(ForwardAsChatCompletions|ForwardAsRawChatCompletions|HandleChatStreamingResponse|ShouldAutoInjectPromptCacheKeyForCompat|DeriveCompatPromptCacheKey|ApplyCodexOAuthTransform|NormalizeCodexToolChoice|GPT61Sol|CCStreamingFromNativeAnthropic|CCBufferedFromNativeAnthropic|OpenAIChatText)' -count=1
go test -tags=embed ./internal/web -run 'TestEmbeddedFrontendBypassesUnversionedChatCompletionsAlias' -count=1
go test ./internal/server/routes -run 'TestGatewayRoutes.*ChatCompletions' -count=1
