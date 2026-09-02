# Generates the Stage 1 fixture dataset and prints the reference values that
# tests/fixtures/stage1/claims.json records as "reported".
# Run: Rscript tests/fixtures/stage1/make_fixture.R
set.seed(4711)

n_per <- 30
dat <- data.frame(
  pid = sprintf("P%03d", 1:(2 * n_per)),
  condition = rep(c("control", "attention"), each = n_per),
  age = round(rnorm(2 * n_per, 24, 4)),
  closeness = c(rnorm(n_per, 3.10, 0.80), rnorm(n_per, 4.20, 0.85))
)
dat$closeness <- round(dat$closeness, 2)

dir.create("tests/fixtures/stage1/data", showWarnings = FALSE, recursive = TRUE)
write.csv(dat, "tests/fixtures/stage1/data/study1.csv", row.names = FALSE)

x <- dat$closeness[dat$condition == "attention"]
y <- dat$closeness[dat$condition == "control"]
tt <- t.test(x, y, var.equal = TRUE)
sp <- sqrt(((length(x) - 1) * var(x) + (length(y) - 1) * var(y)) /
             (length(x) + length(y) - 2))
d <- (mean(x) - mean(y)) / sp

cat(sprintf("mean_attention = %.2f\n", mean(x)))
cat(sprintf("sd_attention   = %.2f\n", sd(x)))
cat(sprintf("mean_control   = %.2f\n", mean(y)))
cat(sprintf("sd_control     = %.2f\n", sd(y)))
cat(sprintf("t(%d) = %.2f\n", tt$parameter, tt$statistic))
cat(sprintf("p = %.3g\n", tt$p.value))
cat(sprintf("d = %.2f\n", d))
