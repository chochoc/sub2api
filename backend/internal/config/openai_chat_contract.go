package config

import "fmt"

type OpenAIChatContractConfig struct {
	Policy              string `mapstructure:"policy"`
	StopMode            string `mapstructure:"stop_mode"`
	DrainTimeoutSeconds int    `mapstructure:"drain_timeout_seconds"`
}

func (c OpenAIChatContractConfig) Validate() error {
	// Zero-value injected configs retain legacy behavior. Loaded configurations
	// have registered defaults, so an explicit zero timeout remains an error.
	if c == (OpenAIChatContractConfig{}) {
		return nil
	}
	if c.Policy != "legacy" && c.Policy != "strict" {
		return fmt.Errorf("gateway.openai_chat_contract.policy must be legacy or strict")
	}
	if c.StopMode != "reject" && c.StopMode != "text" {
		return fmt.Errorf("gateway.openai_chat_contract.stop_mode must be reject or text")
	}
	if c.DrainTimeoutSeconds < 1 || c.DrainTimeoutSeconds > 300 {
		return fmt.Errorf("gateway.openai_chat_contract.drain_timeout_seconds must be between 1 and 300")
	}
	return nil
}
