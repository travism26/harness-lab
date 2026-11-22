package lab.springsandbox.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class PassRateTest {

    @Test
    void roundsHalfUp() {
        assertEquals(75, new PassRate(3, 4).percent());
        assertEquals(33, new PassRate(1, 3).percent());
        assertEquals(67, new PassRate(2, 3).percent());
        assertEquals(0, new PassRate(0, 3).percent());
        assertEquals(100, new PassRate(4, 4).percent());
        assertEquals(13, new PassRate(1, 8).percent());
    }

    @Test
    void rejectsZeroTotal() {
        assertThrows(IllegalArgumentException.class, () -> new PassRate(0, 0));
    }

    @Test
    void rejectsNegativeTotal() {
        assertThrows(IllegalArgumentException.class, () -> new PassRate(0, -1));
    }

    @Test
    void rejectsNegativePassed() {
        assertThrows(IllegalArgumentException.class, () -> new PassRate(-1, 4));
    }

    @Test
    void rejectsPassedAboveTotal() {
        assertThrows(IllegalArgumentException.class, () -> new PassRate(5, 4));
    }
}
