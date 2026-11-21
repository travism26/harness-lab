package lab.springsandbox.domain;

/** A count of passed checks out of a non-empty total. */
public record PassRate(int passed, int total) {

    /** Rejects a total below 1 and a passed count outside 0..total. */
    public PassRate {
        if (total < 1) {
            throw new IllegalArgumentException("total must be at least 1: " + total);
        }
        if (passed < 0 || passed > total) {
            throw new IllegalArgumentException(
                    "passed must be between 0 and total: " + passed + " of " + total);
        }
    }

    /** Returns the whole-number percentage, rounded half up. */
    public int percent() {
        return (int) ((passed * 100L * 2 + total) / (total * 2L));
    }
}
