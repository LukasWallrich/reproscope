# Independent reference calculations for the frozen synthetic fixture.
# Run from the repository root. Requires WRS2 and ppcor; no model/API calls.
args <- commandArgs(trailingOnly=TRUE)
d <- read.csv(if (length(args)) args[1] else "tests/fixtures/multiverse_verification/study.csv")
print(WRS2::yuend(d$a, d$b, tr=.2))
print(ppcor::pcor.test(d$y, d$x, d$z))
print(ppcor::spcor.test(d$y, d$x, d$z))

delta <- d$a-d$b
g <- floor(.2*length(delta)); h <- length(delta)-2*g
se <- sqrt((length(delta)-1)*WRS2::winvar(delta,.2)/(h*(h-1)))
effect <- mean(delta,trim=.2)
dput(list(trimmed_difference=effect, se=se, df=h-1,
          p=2*pt(-abs(effect/se),h-1)))

knots <- quantile(d$z,c(.1,.5,.9))
Z <- splines::ns(d$z,knots=knots[2],Boundary.knots=knots[c(1,3)])
r <- cor(resid(lm(d$y~Z)),resid(lm(d$x~Z)))
df <- nrow(d)-4
dput(list(spline_partial=r, df=df, p=2*pt(-abs(r*sqrt(df/(1-r*r))),df)))

signed <- 1:28; signed[1:10] <- -signed[1:10]
dput(list(signed_rank_28=wilcox.test(signed,exact=TRUE)$p.value))
