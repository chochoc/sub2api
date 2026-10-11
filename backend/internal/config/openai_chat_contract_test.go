package config

import (
	"github.com/stretchr/testify/require"
	"testing"
)

func TestOpenAIChatContractConfigValidation(t *testing.T) {
	require.NoError(t, (OpenAIChatContractConfig{}).Validate())
	for _, policy := range []string{"legacy", "strict"} {
		for _, mode := range []string{"reject", "text"} {
			require.NoError(t, (OpenAIChatContractConfig{Policy: policy, StopMode: mode, DrainTimeoutSeconds: 30}).Validate())
		}
	}
	for _, c := range []OpenAIChatContractConfig{
		{Policy: "other", StopMode: "reject", DrainTimeoutSeconds: 30},
		{Policy: "strict", StopMode: "other", DrainTimeoutSeconds: 30},
		{Policy: "strict", StopMode: "text", DrainTimeoutSeconds: 0},
		{Policy: "strict", StopMode: "text", DrainTimeoutSeconds: 301},
	} {
		require.Error(t, c.Validate())
	}
}

func TestOpenAIChatContractConfigEnvironment(t *testing.T) {
	resetViperWithJWTSecret(t)
	cfg, err := Load()
	require.NoError(t, err)
	require.Equal(t, OpenAIChatContractConfig{Policy: "legacy", StopMode: "reject", DrainTimeoutSeconds: 30}, cfg.Gateway.OpenAIChatContract)
	t.Setenv("GATEWAY_OPENAI_CHAT_CONTRACT_POLICY", "strict")
	t.Setenv("GATEWAY_OPENAI_CHAT_CONTRACT_STOP_MODE", "text")
	t.Setenv("GATEWAY_OPENAI_CHAT_CONTRACT_DRAIN_TIMEOUT_SECONDS", "12")
	cfg, err = Load()
	require.NoError(t, err)
	require.Equal(t, OpenAIChatContractConfig{Policy: "strict", StopMode: "text", DrainTimeoutSeconds: 12}, cfg.Gateway.OpenAIChatContract)
	t.Setenv("GATEWAY_OPENAI_CHAT_CONTRACT_DRAIN_TIMEOUT_SECONDS", "0")
	_, err = Load()
	require.Error(t, err)
}
