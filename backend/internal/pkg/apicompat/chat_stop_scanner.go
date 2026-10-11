package apicompat

import "strings"

// TextStopScanner scans decoded UTF-8 text. Stops must have been validated by
// ParseChatStop. Each request owns its scanner; it is not safe for concurrent use.
type TextStopScanner struct {
	stops   []string
	pending string
	matched bool
}

func NewTextStopScanner(stops []string) *TextStopScanner {
	return &TextStopScanner{stops: append([]string(nil), stops...)}
}

func (s *TextStopScanner) Matched() bool { return s.matched }

func (s *TextStopScanner) Push(delta string) (string, bool) {
	if s.matched {
		return "", true
	}
	s.pending += delta
	return s.scan(false)
}

func (s *TextStopScanner) Finish() (string, bool) {
	if s.matched {
		return "", true
	}
	return s.scan(true)
}

func (s *TextStopScanner) scan(final bool) (string, bool) {
	text := s.pending
	for i := range text {
		suffix := text[i:]
		partial := false
		for _, stop := range s.stops {
			if strings.HasPrefix(suffix, stop) {
				s.pending, s.matched = "", true
				return text[:i], true
			}
			if !final && len(suffix) < len(stop) && strings.HasPrefix(stop, suffix) {
				partial = true
			}
		}
		if partial {
			s.pending = text[i:]
			return text[:i], false
		}
	}
	s.pending = ""
	return text, false
}
